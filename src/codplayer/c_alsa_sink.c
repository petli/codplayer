/* c_alsa_sink - C implementation with high-priority player thread
 *
 * Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
 *
 *
 * This was originally based on pyalsaaudio, but by now there's
 * nothing left of that code but the module setup at the very end.
 * Still, that code had this attribution:
 *
 * Contributed by Unispeed A/S (http://www.unispeed.com)
 * Author: Casper Wilstup (cwi@aves.dk)
 *
 * Bug fixes and maintenance by Lars Immisch <lars@ibp.de>
 * 
 * License: Python Software Foundation License
 */

#define PY_SSIZE_T_CLEAN
#include "Python.h"

#if PY_MAJOR_VERSION < 3 && PY_MINOR_VERSION < 6
#include "stringobject.h"
#define PyUnicode_FromString PyString_FromString
#endif

#include <alsa/asoundlib.h>
#include <stdio.h>
#include <pthread.h>
#include <sched.h>


/* Will run on approx 10Hz for PCM */
#define PERIOD_FRAMES 4096
#define PERIOD_MSECS 100

#define BUFFER_SECONDS 5
#define MAX_PERIODS_PER_SECOND 40

typedef enum {
    SINK_CLOSED,
    SINK_STARTING,
    SINK_PLAYING,
    SINK_DRAINING,
    SINK_SHUTDOWN,
} sink_state_t;


typedef struct {
    PyObject_HEAD;

    char *cardname;
  
    /* Parent device object methods */
    PyObject *log;
    PyObject *debug;

    pthread_t thread;
    
    /* Buffer between playing thread and Python env */

    /* The rest of this structure is protected by
       a mutex, and data exchanged with cond signalling.
    */
    pthread_mutex_t mutex;
    pthread_cond_t cond;

    sink_state_t state;
    int paused;
    snd_pcm_t *handle;         /* NULL if closed */

    /* Current sound format, set by start() */
    int channels;
    int rate;
    int big_endian;

    /* Actual hardware settings, set by thread_set_format() */
    int period_frames;
    int swap_bytes;

    const char *device_error;  /* Current error, or NULL */

    /* Allow simple logging by passing static strings from the thread
       to the Python environment. Reset when logged.  There's a small
       chance that messages are lost, but that's fine.
    */
    const char *log_message;
    const char *log_param;

    /* All buffer parameters are in bytes, not frames or periods.
     * play_pos and data_end are < buffer_size.
     */
    int period_size;
    int buffer_size;
    int play_pos;
    int data_end;
    int data_size;

    /* Frames buffered waiting to be played. */
    unsigned char *buffer;

    /* Packet objects mapping to each period in the buffer */ 
    PyObject **packets;

    /* End of thread buffer structure */


    /* Thread private data */

    /* Parameters for what HW does */

    /* Performanace logging */
    FILE *thread_perf_log;

} alsa_thread_t;


#define BEGIN_LOCK(self) pthread_mutex_lock(&(self)->mutex)
#define END_LOCK(self) pthread_mutex_unlock(&(self)->mutex)
#define NOTIFY(self) pthread_cond_broadcast(&(self)->cond)
#define WAIT(self) pthread_cond_wait(&(self)->cond, &(self)->mutex)


static PyObject* alsa_sink_start(alsa_thread_t *self, PyObject *args);
static PyObject* alsa_sink_stop(alsa_thread_t *self, PyObject *args);
static PyObject* alsa_sink_add_packet(alsa_thread_t *self, PyObject *args);
static PyObject* alsa_sink_drain(alsa_thread_t *self, PyObject *args);
static PyObject* alsa_sink_pause(alsa_thread_t *self, PyObject *args);
static PyObject* alsa_sink_resume(alsa_thread_t *self, PyObject *args);

static void copy_and_swap(unsigned char *dest, int pos,
                          const unsigned char *src, int length);
static int thread_open_device(alsa_thread_t *self);
static int thread_set_format(alsa_thread_t *self, snd_pcm_t *handle);
static void* thread_main(void *arg);
static void thread_loop(alsa_thread_t *self);
static void thread_play_once(alsa_thread_t *self);


/* Translate a card id to a ALSA cardname 

   Returns a newly allocated string.
*/
static char *translate_cardname(char *name)
{
    static char dflt[] = "default";
    char *full = NULL;
    
    if (!name || !strcmp(name, dflt))
        return strdup(dflt);
    
    // If we find a colon, we assume it is a real ALSA cardname
    if (strchr(name, ':'))
        return strdup(name);

    full = malloc(strlen("default:CARD=") + strlen(name) + 1);  
    sprintf(full, "default:CARD=%s", name);

    return full;
}


static PyTypeObject CAlsaSinkType;
static PyObject *CAlsaSinkError;

static PyObject* get_parent_func(PyObject *parent, const char *attr)
{
    PyObject *func;

    func = PyObject_GetAttrString(parent, attr);
    if (func == NULL)
        return NULL;

    if (!PyCallable_Check(func))
    {
	Py_DECREF(func);
        return PyErr_Format(CAlsaSinkError,
			    "parent.%s is not a callable function",
			    attr);
    }

    return func;
}


/* Log and debug methods are not useable in the playing thread, since
 * they pass messages into Python.
 */
static int alsa_log1(alsa_thread_t *self, const char *msg)
{
    PyObject *res = PyObject_CallFunction(
        self->log, "ss", "c_alsa_sink: {0}", msg);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_log2(alsa_thread_t *self, const char *msg, const char *value)
{
    PyObject *res = PyObject_CallFunction(
        self->log, "sss", "c_alsa_sink: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


/*
static int alsa_logi(alsa_thread_t *self, const char *msg, int value)
{
    PyObject *res = PyObject_CallFunction(
        self->log, "ssi", "c_alsa_sink: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}
*/

static int alsa_debug1(alsa_thread_t *self, const char *msg)
{
    PyObject *res = PyObject_CallFunction(
        self->debug, "ss", "c_alsa_sink: {0}", msg);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int alsa_debug2(alsa_thread_t *self, const char *msg, const char *value)
{
    PyObject *res = PyObject_CallFunction(
        self->debug, "sss", "c_alsa_sink: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int alsa_debugi(alsa_thread_t *self, const char *msg, int value)
{
    PyObject *res = PyObject_CallFunction(
        self->debug, "ssi", "c_alsa_sink: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


/*
 * Functions for passing messages out of the playing thread
 */

static void set_device_error(alsa_thread_t *self, const char *error)
{
    /* LOCK SCOPE: only to be called while mutex is locked */

    self->device_error = error;
    NOTIFY(self);
}


static void set_log_message(alsa_thread_t *self, const char *message, const char *param)
{
    {/* LOCK SCOPE */
        BEGIN_LOCK(self);

        self->log_message = message;
        self->log_param = param;
        NOTIFY(self);

        END_LOCK(self);
    }
}


/*
 * Object constructor
 */
static PyObject *
alsa_thread_new(PyTypeObject *type, PyObject *args, PyObject *kwds) 
{
    int res;
    alsa_thread_t *self;
    PyObject *parent = NULL;
    char *cardname = NULL;
    int start_without_device = 0;
    int log_performance = 0;
    snd_pcm_t *handle = NULL;
    pthread_attr_t thread_attr;
    struct sched_param sched;
    
    if (!PyArg_ParseTuple(args, "Osii:CAlsaSink",
                          &parent, &cardname, &start_without_device, &log_performance))
        return NULL;
    

    if (!(self = (alsa_thread_t *)PyObject_New(alsa_thread_t, &CAlsaSinkType)))
        return NULL;
    
    self->cardname = translate_cardname(cardname);

    /* Get the parent methods we need for logging and reporting back */
    self->log = get_parent_func(parent, "log");
    if (self->log == NULL)
        return NULL;    

    self->debug = get_parent_func(parent, "debug");
    if (self->debug == NULL)
        return NULL;    

    if (log_performance)
    {
        self->thread_perf_log = fopen("/tmp/cod_alsa_thread.log", "wt");
    }
    else
    {
        self->thread_perf_log = NULL;
    }


    self->thread = 0;
    
    pthread_mutex_init(&(self->mutex), NULL);
    pthread_cond_init(&(self->cond), NULL);

    self->state = SINK_CLOSED;
    self->paused = 0;
    self->handle = 0;

    self->channels = 0;
    self->rate = 0;
    self->big_endian = 0;
    self->period_frames = 0;
    self->swap_bytes = 0;

    self->device_error = NULL;
    self->log_message = NULL;
    self->log_param = NULL;

    /* Buffer is set up when we know the format */
    self->buffer_size = 0;
    self->play_pos = 0;
    self->data_end = 0;
    self->data_size = 0;
    self->buffer = NULL;

    /* But we grab this right away with some assumptions about
     * what period size we might end up with */
    self->packets = calloc(sizeof(PyObject*), BUFFER_SECONDS * MAX_PERIODS_PER_SECOND);
    if (self->packets == NULL)
        return PyErr_NoMemory();


    /* Try to open card straight away to verify access rights etc */

    alsa_debug2(self, "opening card", self->cardname);
	
    Py_BEGIN_ALLOW_THREADS
    res = snd_pcm_open(&handle, self->cardname,
                       SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
    Py_END_ALLOW_THREADS
    
    if (res < 0) 
    {
	if (start_without_device)
	{
	    alsa_log2(self, "error opening card", snd_strerror(res));
	    alsa_log1(self, "proceeding since start_without_device = True");
	    self->handle = 0;
            set_device_error(self, snd_strerror(res));
	}
	else
	{
            PyErr_Format(CAlsaSinkError, "can't open %s: %s (%d)",
                         self->cardname, snd_strerror(res), res);
	    return NULL;
	}
    }
    else
    {
        // Close it again, we'll reopen it when it's needed
        snd_pcm_close(handle);
        set_device_error(self, NULL);
    }

    /* Ready to kick off thread */

    /* Try to start with elevated priority (without going to extremes) */
    if (pthread_attr_init(&thread_attr) != 0)
        return PyErr_Format(CAlsaSinkError, "pthread_attr_init: %s",
                            strerror(errno));

    if (pthread_attr_setinheritsched(&thread_attr,
                                     PTHREAD_EXPLICIT_SCHED) != 0)
        return PyErr_Format(CAlsaSinkError, "pthread_attr_setinheritsched: %s",
                            strerror(errno));
        
    if (pthread_attr_setschedpolicy(&thread_attr, SCHED_RR) != 0)
        return PyErr_Format(CAlsaSinkError, "pthread_attr_setschedpolicy: %s",
                            strerror(errno));
        
    sched.sched_priority = sched_get_priority_min(SCHED_RR);
    if (pthread_attr_setschedparam(&thread_attr, &sched) != 0)
        return PyErr_Format(CAlsaSinkError, "pthread_attr_setschedparam: %s",
                            strerror(errno));
    
    if (pthread_create(&self->thread, &thread_attr, thread_main, self) != 0)
    {
        if (errno == EPERM)
        {
            alsa_log1(self, "couldn't start realtime thread, falling back on a normal thread");
            
            if (pthread_create(&self->thread, NULL, thread_main, self) != 0)
            {
                PyErr_Format(CAlsaSinkError, "couldn't start thread (try 2): %s",
                             strerror(errno));
                return NULL;
            }
        }
        else
        {
            if (pthread_create(&self->thread, NULL, thread_main, self) != 0)
            {
                PyErr_Format(CAlsaSinkError, "couldn't start thread: %s",
                             strerror(errno));
                return NULL;
            }
        }            
    }

    pthread_attr_destroy(&thread_attr);

    return (PyObject *)self;
}


static void alsa_thread_dealloc(alsa_thread_t *self) 
{
    // stop is safe to call in all states to get rid of the pcm handle
    alsa_sink_stop(self, Py_BuildValue("()"));

    {/* LOCK SCOPE */
        BEGIN_LOCK(self);

        self->state = SINK_SHUTDOWN;
        NOTIFY(self);

        END_LOCK(self);
    }

    if (pthread_join(self->thread, NULL) == 0)
    {
        free(self->cardname);
        free(self->buffer);

        // TODO: decref the packet buffer

        Py_XDECREF(self->log);
        Py_XDECREF(self->debug);
        PyObject_Del(self);
    }
    else
    {
        fprintf(stderr, "c_alsa_sink: couldn't join player thread, not freeing memory\n");
    }
}


static PyObject*
alsa_sink_start(alsa_thread_t *self, PyObject *args)
{
    int channels = 0;
    int bytes_per_sample = 0;
    int rate = 0;
    int big_endian = 0;
    const char *error = NULL;

    if (!PyArg_ParseTuple(args, "iiii:CAlsaSink.start",
                          &channels, &bytes_per_sample, &rate, &big_endian))
    {
        return NULL;
    }

    if (bytes_per_sample != 2)
    {
        return PyErr_Format(CAlsaSinkError,
                            "only supports 2 bytes per sample, got %d",
                            bytes_per_sample);
    }

    {/* LOCK SCOPE */
        BEGIN_LOCK(self);

        if (self->state == SINK_CLOSED)
        {
            alsa_debug1(self, "starting sink");
            self->state = SINK_STARTING;
            self->paused = 0;
            self->channels = channels;
            self->rate = rate;
            self->big_endian = big_endian;

            // TODO: given the state sync we could open the device
            // here and thus get an exception back into python
            // directly, but for now let the player thread do that.

            NOTIFY(self);
        }
        else
        {
            error = "invalid state";
        }

        END_LOCK(self);
    }

    if (error)
    {
        return PyErr_Format(CAlsaSinkError, "start: %s", error);
    }

    Py_RETURN_NONE;
}


static PyObject *
alsa_sink_stop(alsa_thread_t *self, PyObject *args)
{
    if (!PyArg_ParseTuple(args,":CAlsaSink.stop"))
    {
        return NULL;
    }

    {/* LOCK SCOPE */
        BEGIN_LOCK(self);

        /* Whenever there's a PCM handle, we drop its buffer and
         * closes it regardless of other state.
         */
        if (self->handle)
        {
            int res;

            alsa_debug1(self, "stop: dropping PCM buffer");
            res = snd_pcm_drop(self->handle);
            if (res < 0)
            {
                alsa_log2(self, "stop: error dropping pcm buffer: %s",
                          strerror(-res));
            }

            alsa_debug1(self, "stop: closing PCM handle");
            snd_pcm_close(self->handle);
            self->handle = 0;
        }

        /* Reset state */
        self->state = SINK_CLOSED;
        self->paused = 0;
        self->channels = 0;
        self->rate = 0;
        self->big_endian = 0;

        self->device_error = NULL;

        self->play_pos = 0;
        self->data_end = 0;
        self->data_size = 0;

        alsa_debug1(self, "sink stopped");

        /* Notify the other threads - not so much the player thread as
         * the transport sink thread that's waiting in
         * playing_once().
         */
        NOTIFY(self);

        END_LOCK(self);
    }

    Py_RETURN_NONE;
}
    

static int
playing_once(
    alsa_thread_t *self,
    PyObject *packet, const unsigned char *data, Py_ssize_t data_size,

    // Return variables
    PyObject **playing_packet, const char **device_error)
{
    int stored = 0;
    const char *log_message = NULL;
    const char *log_param = NULL;
    int first_data_period = -1;
    int last_data_period = -1;
    int play_period = -1;
    int i;

    {/* LOCK SCOPE */
        Py_BEGIN_ALLOW_THREADS;
        BEGIN_LOCK(self);

        /* We don't touch any python objects until the end of this
         * lock scope, so allow other threads to run throughout
         * the interaction with the play thread.
         */

        if (self->state == SINK_STARTING)
        {
            /* Wait for thread to open the device */
            Py_BLOCK_THREADS;
            alsa_debug1(self, "starting, waiting for sink to be ready");
            Py_UNBLOCK_THREADS;

            WAIT(self);
        }
            
        if (self->state == SINK_PLAYING || self->state == SINK_DRAINING)
        {
            if (data != NULL)
            {
                if (self->data_size >= self->buffer_size)
                {
                    /* Wait for more room in buffer */
                    WAIT(self);
                }

                if (self->state != SINK_CLOSED && self->data_size < self->buffer_size)
                {
                    /* Can fit more data */

                    int buffer_free = self->buffer_size - self->data_size;
                    
                    stored = data_size;
                    if (stored > buffer_free)
                        stored = buffer_free;

                    /* But don't wrap the end of the buffer */
                    if (self->data_end + stored > self->buffer_size)
                        stored = self->buffer_size - self->data_end;

                    first_data_period = self->data_end / self->period_size;
                    last_data_period = (self->data_end + stored) / self->period_size;
                    
                    if (self->swap_bytes)
                    {
                        copy_and_swap(self->buffer, self->data_end, data, stored);
                    }
                    else
                    {
                        memcpy(self->buffer + self->data_end, data, stored);
                    }

                    self->data_end = (self->data_end + stored) % self->buffer_size;
                    self->data_size += stored;

                    /* Tell playing thread about the new data */
                    NOTIFY(self);
                }
            }
            else
            {
                /* Reached the end of the stream.  Pad out to a whole
                 * period, if necessary.  We know this will fit, since
                 * the play thread always reads in whole periods.
                 */
                int partial = self->data_end % self->period_size;

                if (partial > 0)
                {
                    memset(self->buffer + self->data_end, 0,
                           self->period_size - partial);
                    self->data_end = (self->data_end + self->period_size - partial) % self->buffer_size;
                    self->data_size += self->period_size - partial;

                    /* Tell playing thread about the new data */
                    NOTIFY(self);
                }
                else
                {
                    /* Wait for updates to playing_packet etc */
                    WAIT(self);
                }
            }
        }

        /* Bring the return parameters out of the lock and into Python land
         */

        if (self->state == SINK_CLOSED)
        {
            /* Tell add_packet()/drain() to return early */
            stored = -1;
        }

        if (self->data_size > 0)
        {
            /* By checking data_size we ensure that we have a valid pointer in self->packets.
             * There are patological cases where this means we can't report progress, but if we don't
             * have data in the buffer when we get to this point we have bigger problems than
             * not updating the player status.
             */
            play_period = self->play_pos / self->period_size;
        }

        *device_error = self->device_error;
        log_message = self->log_message;
        log_param = self->log_param;

        /* Reset the log message now that we got it */
        self->log_message = NULL;
        self->log_param = NULL;

        END_LOCK(self);
        Py_END_ALLOW_THREADS;
    }
    
    if (first_data_period >= 0)
    {
        /* Replace references to buffered packets with this one.
         *
         * BTW, this is only safe if only one Python thread is calling
         * this object, which the Sink API guarantees us.
         */

        if (first_data_period == last_data_period)
        {
            /* Always write one reference to the packet, even in the
             * case where we add less than a whole period
             */
            last_data_period = first_data_period + 1;
        }

        for (i = first_data_period; i < last_data_period; i++)
        {
            Py_XDECREF(self->packets[i]);
            
            self->packets[i] = packet;
            Py_INCREF(packet);
        }
    }

    if (play_period >= 0)
    {
        /* The reference stays with the buffer, and gets increased by
         * Py_BuildValue when returned from add_packet()/drain()
         */
        *playing_packet = self->packets[play_period];
    }
    
    if (*playing_packet == NULL)
    {
        // TODO: is this really necessary?
        *playing_packet = Py_None;
    }
    
    if (log_message)
    {
        if (log_param)
            alsa_log2(self, log_message, log_param);
        else
            alsa_log1(self, log_message);
    }

    return stored;
}    
    

static void
copy_and_swap(unsigned char *dest, int pos,
              const unsigned char *src, int length)
{
    int i;
    for (i = pos; i < pos + length; i++, src++)
    {
        /* Use XOR to flip odd to even and vice versa.  This means we
         * might in patological cases write a byte ahead of what we
         * strictly speaking are allowed to, but since we know that
         * the play thread always consumes whole periods and not odd
         * bytes this is safe.
         */
        dest[i ^ 1] = *src;
    }
}


static PyObject *
alsa_sink_add_packet(alsa_thread_t *self, PyObject *args)
{
    const unsigned char *data = NULL;
    Py_ssize_t data_size = 0;
    PyObject *packet = NULL;
    int stored = 0;
    PyObject *prev_playing_packet = NULL;
    PyObject *playing_packet = NULL;
    const char *prev_device_error = NULL;
    const char *device_error = NULL;

    if (!PyArg_ParseTuple(args, "s#O:CAlsaSink.add_packet",
                          &data, &data_size, &packet))
        return NULL;


    /* We'll keep running here until something happens that may
     * require the Transport state to be updated.  Return on:
     *
     * - The sink state is CLOSED (i.e. stop() was called)
     * - Some data has been stored into the buffer
     * - The current packet being played has changed
     * - The device error has changed
     */

    do
    {
        prev_playing_packet = playing_packet;
        prev_device_error = device_error;

        stored = playing_once(self, packet, data, data_size,
                              &playing_packet, &device_error);
    }
    while (stored == 0
           && (prev_playing_packet == NULL || prev_playing_packet == playing_packet)
           && (prev_device_error == NULL || prev_device_error == device_error));

    // TODO: should remember prev_playing_packet/prev_device_error in self across calls

    if (stored < 0)
    {
        alsa_debug1(self, "add_packet: sink closed");

        /* Used by playing_once when state is CLOSED, translate into
         * add_packet() API.
         */
        stored = 0;
    }

    // TODO: remember device_error to avoid spawning new strings all the time

    return Py_BuildValue("iOs", stored, playing_packet, device_error);
}


static PyObject *
alsa_sink_drain(alsa_thread_t *self, PyObject *args)
{
    int stored = 0;
    PyObject *prev_playing_packet = NULL;
    PyObject *playing_packet = NULL;
    const char *prev_device_error = NULL;
    const char *device_error = NULL;

    if (!PyArg_ParseTuple(args, ":CAlsaSink.drain"))
        return NULL;

    {
        BEGIN_LOCK(self);

        if (self->state == SINK_PLAYING)
        {
            alsa_debug1(self, "drain: switching to state draining");

            self->state = SINK_DRAINING;
            NOTIFY(self);
        }
        else if (self->state != SINK_DRAINING)
        {
            alsa_debugi(self, "drain: draining finished in state %d", self->state);

            // Already stopped
            stored = -1;
        }

        END_LOCK(self);
    }

    if (stored < 0)
    {
        /* Already closed, tell Transport we're done */
        Py_RETURN_NONE;
    }

    do
    {
        prev_playing_packet = playing_packet;
        prev_device_error = device_error;

        stored = playing_once(self, NULL, NULL, 0,
                              &playing_packet, &device_error);
    }
    while (stored == 0
           && (prev_playing_packet == NULL || prev_playing_packet == playing_packet)
           && (prev_device_error == NULL || prev_device_error == device_error));

    if (stored < 0)
    {
        alsa_debug1(self, "drain: sink closed");

        /* Now closed, tell Transport we're done */
        Py_RETURN_NONE;
    }

    // TODO: should remember prev_playing_packet/prev_device_error in self across calls

    // TODO: remember device_error to avoid spawning new strings all the time

    return Py_BuildValue("Os", playing_packet, device_error);
}


static PyObject *
alsa_sink_pause(alsa_thread_t *self, PyObject *args)
{
    int res = 0;

    if (!PyArg_ParseTuple(args,":CAlsaSink.pause"))
        return NULL;

    { /* LOCK SCOPE */
        BEGIN_LOCK(self);

        if (self->state != SINK_CLOSED)
        {
            if (!self->paused && self->handle)
            {
                res = snd_pcm_pause(self->handle, 1);
            }

            if (res == 0)
            {
                self->paused = 1;
            }
        }

        END_LOCK(self);
    }
  
    if (res < 0) 
    {
        alsa_log2(self, "error pausing pcm: %s", snd_strerror(res));
    }

    return PyBool_FromLong(res == 0);
}


static PyObject *
alsa_sink_resume(alsa_thread_t *self, PyObject *args)
{
    int res = 0;

    if (!PyArg_ParseTuple(args,":CAlsaSink.resume"))
        return NULL;

    { /* LOCK SCOPE */
        BEGIN_LOCK(self);

        if (self->state != SINK_CLOSED)
        {
            if (self->paused && self->handle)
            {
                res = snd_pcm_pause(self->handle, 0);
            }

            /* Always consider ourselves resumed */
            self->paused = 0;

            /* Wake up player thread again */
            NOTIFY(self);
        }

        END_LOCK(self);
    }

    if (res < 0)
    {
        alsa_log2(self, "error resuming pcm: %s", snd_strerror(res));
    }

    Py_RETURN_NONE;
}


static void* thread_main(void *arg)
{
    alsa_thread_t *self = arg;
    struct sched_param sched;
    int policy;

    pthread_getschedparam(pthread_self(), &policy, &sched);
    if (policy == SCHED_RR) 
        set_log_message(self, "running at SCHED_RR priority", NULL);
    else if (policy == SCHED_FIFO) 
        set_log_message(self, "running at SCHED_FIFO priority", NULL);
    else
        set_log_message(self, "running at normal priority", NULL);

    thread_loop(self);

    { /* LOCK SCOPE */
        BEGIN_LOCK(self);

        if (self->state != SINK_SHUTDOWN)
        {
            self->log_message = "player thread died";
            self->log_param = NULL;
            self->device_error = "player thread died";
            NOTIFY(self);
        }
        
        END_LOCK(self);
    }

    return NULL;
}


static void thread_loop(alsa_thread_t *self)
{
    int keep_running = 1;

    while (keep_running)
    { /* LOCK SCOPE */
        BEGIN_LOCK(self);

        switch (self->state)
        {
        case SINK_CLOSED:
            /* Just wait for transport to start us */
            WAIT(self);
            break;

        case SINK_STARTING:
        case SINK_PLAYING:
            if (self->paused)
            {
                /* Don't push stuff into the device when it is paused.
                 * Though it shouldn't accept it, let's not provoke it.
                 * Just wait for state to change.
                 */
                WAIT(self);
            }
            else
            {
                thread_play_once(self);
            }
            break;

        case SINK_DRAINING:
            if (self->paused)
            {
                WAIT(self);
            }
            else if (self->data_size > 0)
            {
                thread_play_once(self);
            }
            else
            {
                /* All our buffered data is done, so drain the stuff
                 * in the PCM buffer.  Wonder how this works when
                 * we're in non-blocking mode?
                 */
                if (self->handle)
                {
                    int res;
                    res = snd_pcm_drain(self->handle);
                    if (res < 0)
                    {
                        self->log_message = "error draining device";
                        self->log_param = snd_strerror(res);
                    }

                    /* Whatever happens, we're done and can close the
                     * device */
                    snd_pcm_close(self->handle);
                    self->handle = NULL;
                }

                self->state = SINK_CLOSED;
                self->paused = 0;
                self->channels = 0;
                self->rate = 0;
                self->big_endian = 0;

                self->device_error = NULL;

                self->play_pos = 0;
                self->data_end = 0;
                self->data_size = 0;

                NOTIFY(self);
            }
            break;

        case SINK_SHUTDOWN:
            keep_running = 0;
            break;
        }

        END_LOCK(self);
    }
}


static void thread_play_once(alsa_thread_t *self)
{
    /* LOCK SCOPE: self->mutex is already locked when this function is
     * called.
     */

    if (self->handle == NULL)
    {
        /* Attempt to (re)open device */
        if (!thread_open_device(self))
        {
            return;
        }
    }

    /* Now we know we have a good pcm handle */

    if (self->data_size < self->period_size)
    {
        /* Wait for data - we can block here as long as needed */
        WAIT(self);
    }

    /* Put as many periods as possible into the pcm device */
    while (self->data_size >= self->period_size)
    {
        struct timespec ts;
        unsigned char *data;
        int res;

        data = self->buffer + self->play_pos;

        /* Suddenly the size argument is frames, not bytes... */
        res = snd_pcm_writei(self->handle, data, self->period_frames);

        switch (res)
        {
        case 0: /* might get this on paused streams? */
        case -EAGAIN:
            /* PCM buffer is full, so sleep about a period and go back
             * to the main loop.
             */
            ts.tv_sec = 0;
            ts.tv_nsec = PERIOD_MSECS * 1000000;
            pthread_cond_timedwait(&self->cond, &self->mutex, &ts);
            return;

        case -EINTR:
        case -EPIPE:
        case -ESTRPIPE:
            res = snd_pcm_recover(self->handle, res, 1);
            break;
        }

        if (res > 0)
        {
            self->play_pos = (self->play_pos + self->period_size) % self->buffer_size;
            self->data_size -= self->period_size;
            NOTIFY(self);
        }
        else if (res < 0)
        {
            snd_pcm_close(self->handle);
            self->handle = NULL;
            self->log_message = "error writing to device";
            self->log_param = snd_strerror(res);
            self->device_error = snd_strerror(res);
            NOTIFY(self);
            return;
        }
    }
}


static int thread_open_device(alsa_thread_t *self)
{
    snd_pcm_t *handle = NULL;

    int res = snd_pcm_open(&handle, self->cardname,
                           SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);

    if (res >= 0)
    {
        if (thread_set_format(self, handle))
        {
            if (self->paused)
            {
                /* Restart device in paused state */
                res = snd_pcm_pause(handle, 1);
            }

            if (res >= 0)
            {
                self->handle = handle;
                self->device_error = NULL;

                if (self->log_message == NULL)
                {
                    self->log_message =
                        (self->state == SINK_STARTING ?
                         "opened device" : "reopened device");
                    self->log_param = (self->swap_bytes ?
                                       "swapping bytes" : "not swapping bytes");
                }

                if (self->state == SINK_STARTING)
                {
                    /* Now we know the transport thread can put frames
                     * into the buffer.
                     */
                    self->state = SINK_PLAYING;
                }

                NOTIFY(self);

                return 1;
            }
            else
            {
                set_device_error(self, snd_strerror(res));
            }
        }
    }
    else
    {
        set_device_error(self, snd_strerror(res));
    }

    /* We only get here on errors */

    if (handle != NULL)
    {
        snd_pcm_close(handle);
    }

    /* Sleep to avoid busy-looping on a bad device */

    END_LOCK(self);
    {
        /* UNLOCKED CONTEXT */
        struct timespec ts;
        ts.tv_sec = 3;
        ts.tv_nsec = 0;
        while (nanosleep(&ts, &ts) < 0 && errno == EINTR)
        { }
    }
    BEGIN_LOCK(self);

    return 0;
}


/* This function may be called in the playing thread, so it can't use
 * any Python stuff.
 */
static int thread_set_format(alsa_thread_t *self, snd_pcm_t *handle)
{
    int res,dir;
    unsigned int set_channels;
    unsigned int set_rate;
    snd_pcm_uframes_t set_period_size;
    snd_pcm_format_t sample_format, set_sample_format;
    unsigned int periods;
    snd_pcm_hw_params_t *hwparams;
        
        
    self->swap_bytes = 0;
    sample_format = self->big_endian ? SND_PCM_FORMAT_S16_BE : SND_PCM_FORMAT_S16_LE;
    periods = 4;

    /* Allocate a hwparam structure on the stack, 
       and fill it with configuration space */
    snd_pcm_hw_params_alloca(&hwparams);

    while (1)
    {
        res = snd_pcm_hw_params_any(handle, hwparams);
        if (res < 0)
        {
            set_device_error(self, snd_strerror(res));
            return 0;
        }

        snd_pcm_hw_params_set_access(handle, hwparams, 
                                     SND_PCM_ACCESS_RW_INTERLEAVED);
        snd_pcm_hw_params_set_format(handle, hwparams, sample_format);
        snd_pcm_hw_params_set_channels(handle, hwparams, self->channels);

        dir = 0;
        snd_pcm_hw_params_set_rate(handle, hwparams, self->rate, dir);
        snd_pcm_hw_params_set_period_size(handle, hwparams, PERIOD_FRAMES, dir);
        snd_pcm_hw_params_set_periods(handle, hwparams, periods, 0);
    
        /* Write it to the device */
        res = snd_pcm_hw_params(handle, hwparams);
        if (res < 0)
        {
            set_device_error(self, snd_strerror(res));
            return 0;
        }

        
        /* Check if the card accepted our settings */
        res = snd_pcm_hw_params_current(handle, hwparams);
        if (res < 0)
        {
            self->log_message = "error querying params";
            self->log_param = snd_strerror(res);
            return 0;
        }

        snd_pcm_hw_params_get_format(hwparams, &set_sample_format);
        snd_pcm_hw_params_get_channels(hwparams, &set_channels);
        snd_pcm_hw_params_get_rate(hwparams, &set_rate, &dir);
        snd_pcm_hw_params_get_period_size(hwparams, &set_period_size, &dir); 
    
        if (self->channels != set_channels)
        {
            set_device_error(self, "couldn't set device param: channels");
            return 0;
        }        

        if (self->rate != set_rate)
        {
            set_device_error(self, "couldn't set device param: rate");
            return 0;
        }        

        if (sample_format == set_sample_format)
        {
            /* Got an OK format */
            break;
        }
        else
        {
            if (!self->swap_bytes)
            {
                /* Retry with the other endianness and swap bytes ourselves */
                sample_format = self->big_endian ? SND_PCM_FORMAT_S16_LE : SND_PCM_FORMAT_S16_BE;
                self->swap_bytes = 1;
            }
            else
            {
                /* Give up */
                set_device_error(self, "couldn't set device param: format");
                return 0;
            }
        }
    }

    /* Just use the period size determined by card.  Now we know it,
     * we can allocate the buffer, or just use an existing one with
     * the right parameters.
     */

    if (self->period_frames != set_period_size)
    {
        /* If rate is too high, the packets array is too small and we can't run */
        if ((self->rate / set_period_size) >= MAX_PERIODS_PER_SECOND)
        {
            set_device_error(self, "period set by device is too small");
            return 0;
        }

        self->period_frames = set_period_size;
            
        int buffer_size = self->rate * BUFFER_SECONDS;
        buffer_size -= buffer_size % self->period_frames;
        buffer_size *= self->channels * 2;

        if (self->buffer)
        {
            /* It's OK to discard anything in the buffer, since that
             * is anyway now the wrong format.
             */
            free(self->buffer);
            self->buffer = NULL;
        }
            
        self->buffer = malloc(buffer_size);
        if (self->buffer == NULL)
        {
            self->log_message = "out of memory allocating buffer";
            self->log_param = "";
            self->device_error = "out of memory allocating buffer";
            return 0;
        }

        self->buffer_size = buffer_size;
        self->period_size = self->period_frames * self->channels * 2;
        self->play_pos = 0;
        self->data_end = 0;
        self->data_size = 0;
    }
    
    return 1;
}


/* CAlsaSink Object Bureaucracy */

static PyMethodDef alsa_thread_methods[] = {
    { "start", (PyCFunction) alsa_sink_start, METH_VARARGS },
    { "stop", (PyCFunction) alsa_sink_stop, METH_VARARGS },
    { "add_packet", (PyCFunction) alsa_sink_add_packet, METH_VARARGS },
    { "drain", (PyCFunction) alsa_sink_drain, METH_VARARGS },
    { "pause", (PyCFunction) alsa_sink_pause, METH_VARARGS },
    { "resume", (PyCFunction) alsa_sink_resume, METH_VARARGS },
    {NULL, NULL}
};

#if PY_VERSION_HEX < 0x02020000 
static PyObject *	 
alsa_thread_getattr(alsa_thread_t *self, char *name) {	 
    return Py_FindMethod(alsa_thread_methods, (PyObject *)self, name);	 
}
#endif

static PyTypeObject CAlsaSinkType = {
#if PY_MAJOR_VERSION < 3
    PyObject_HEAD_INIT(&PyType_Type)
    0,                              /* ob_size */
#else
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
#endif
    "alsaaudio.CAlsaSink",                /* tp_name */
    sizeof(alsa_thread_t),              /* tp_basicsize */
    0,                              /* tp_itemsize */
    /* methods */    
    (destructor) alsa_thread_dealloc,   /* tp_dealloc */
    0,                              /* print */
#if PY_VERSION_HEX < 0x02020000
    (getattrfunc)alsa_thread_getattr,   /* tp_getattr */
#else
    0,                              /* tp_getattr */
#endif
    0,                              /* tp_setattr */
    0,                              /* tp_compare */ 
    0,                              /* tp_repr */
    0,                              /* tp_as_number */
    0,                              /* tp_as_sequence */
    0,                              /* tp_as_mapping */
    0,                              /* tp_hash */
    0,                              /* tp_call */
    0,                              /* tp_str */
#if PY_VERSION_HEX >= 0x02020000 
    PyObject_GenericGetAttr,        /* tp_getattro */
#else
    0,                              /* tp_getattro */
#endif
    0,                              /* tp_setattro */
    0,                              /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,             /* tp_flags */
    "ALSA player thread.",             /* tp_doc */
    0,					          /* tp_traverse */
    0,					          /* tp_clear */
    0,					          /* tp_richcompare */
    0,					          /* tp_weaklistoffset */
    0,					          /* tp_iter */
    0,					          /* tp_iternext */
    alsa_thread_methods,		          /* tp_methods */
    0,			                  /* tp_members */
};



/******************************************/
/* Module initialization                  */
/******************************************/

static PyMethodDef c_alsa_sink_methods[] = {
    { 0, 0 },
};


#if PY_MAJOR_VERSION >= 3

#define _EXPORT_INT(mod, name, value) \
  if (PyModule_AddIntConstant(mod, name, (long) value) == -1) return NULL;

static struct PyModuleDef c_alsa_sink_module = {
    PyModuleDef_HEAD_INIT,
    "c_alsa_sink",
    NULL,
    -1,
    c_alsa_sink_methods,
    0,  /* m_reload */
    0,  /* m_traverse */
    0,  /* m_clear */
    0,  /* m_free */
};

#else

#define _EXPORT_INT(mod, name, value) \
  if (PyModule_AddIntConstant(mod, name, (long) value) == -1) return;

#endif // 3.0

#if PY_MAJOR_VERSION < 3
void initc_alsa_sink(void)
#else
PyObject *PyInit_c_alsa_sink(void)
#endif
{
    PyObject *m;
    CAlsaSinkType.tp_new = alsa_thread_new;

    PyEval_InitThreads();

#if PY_MAJOR_VERSION < 3
    m = Py_InitModule3("c_alsa_sink", c_alsa_sink_methods, "");
    if (!m) 
        return;
#else

    m = PyModule_Create(&c_alsa_sink_module);
    if (!m) 
        return NULL;

#endif

    CAlsaSinkError = PyErr_NewException("c_alsa_sink.CAlsaSinkError", NULL,
                                        NULL);
    if (!CAlsaSinkError)
#if PY_MAJOR_VERSION < 3
        return;
#else
        return NULL;
#endif

    /* Each call to PyModule_AddObject decrefs it; compensate: */

    Py_INCREF(&CAlsaSinkType);
    PyModule_AddObject(m, "CAlsaSink", (PyObject *)&CAlsaSinkType);
  
    Py_INCREF(CAlsaSinkError);
    PyModule_AddObject(m, "CAlsaSinkError", CAlsaSinkError);


#if PY_MAJOR_VERSION >= 3
    return m;
#endif
}


/*
  Local Variables:
  c-file-style: "stroustrup"
  indent-tabs-mode:nil
  End:
*/
