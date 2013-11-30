/* cod_alsa_device - ALSA thread implementation, based on pyalsaaudio
 * but now heavily modified.
 *
 * Original module info:
 *
 * alsaaudio -- Python interface to ALSA (Advanced Linux Sound Architecture).
 *              The standard audio API for Linux since kernel 2.6
 *
 * Contributed by Unispeed A/S (http://www.unispeed.com)
 * Author: Casper Wilstup (cwi@aves.dk)
 *
 * Bug fixes and maintenance by Lars Immisch <lars@ibp.de>
 * 
 * License: Python Software Foundation License
 *
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

#define BUFFER_SECONDS 5
#define MAX_PERIODS_PER_SECOND 40

typedef struct {
    PyObject_HEAD;

    int pcmtype;
    int pcmmode;
    char *cardname;
  
    /* Parent device object methods */
    PyObject *log;
    PyObject *debug;

    /* Performanace logging */
    FILE *thread_perf_log;

    /* Sound format */
    int channels;
    int rate;
    int big_endian;

    /* Parameters for what HW does */
    int period_frames;
    int swap_bytes;

    pthread_t thread;
    
    /* Buffer between playing thread and Python env */

    /* The rest of this structure is protected by
       a mutex, and data exchanged with cond signalling.
    */
    pthread_mutex_t mutex;
    pthread_cond_t cond;

    snd_pcm_t *handle;         /* NULL if closed */
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
    int play_size;
    int data_end;
    int data_size;

    /* Frames buffered waiting to be played. */
    unsigned char *buffer;

    /* Packet objects mapping to each period in the buffer */ 
    PyObject **packets;

    /* End of thread buffer structure */
    
} alsa_thread_t;


#define BEGIN_LOCK(self) pthread_mutex_lock(&(self)->mutex)
#define END_LOCK(self) pthread_mutex_unlock(&(self)->mutex)
#define NOTIFY(self) pthread_cond_broadcast(&(self)->cond)


static int thread_set_format(alsa_thread_t *self, snd_pcm_t *handle);
static void* thread_main(void *arg);
static void thread_loop(alsa_thread_t *self);


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


static PyTypeObject AlsaThreadType;
static PyObject *AlsaThreadError;

static PyObject* get_parent_func(PyObject *parent, const char *attr)
{
    PyObject *func;

    func = PyObject_GetAttrString(parent, attr);
    if (func == NULL)
        return NULL;

    if (!PyCallable_Check(func))
    {
	Py_DECREF(func);
        return PyErr_Format(AlsaThreadError,
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
	self->log, "ss", "cod_alsa_device: {0}", msg);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_log2(alsa_thread_t *self, const char *msg, const char *value)
{
    PyObject *res = PyObject_CallFunction(
	self->log, "sss", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int alsa_logi(alsa_thread_t *self, const char *msg, int value)
{
    PyObject *res = PyObject_CallFunction(
	self->log, "ssi", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int alsa_debug1(alsa_thread_t *self, const char *msg)
{
    PyObject *res = PyObject_CallFunction(
	self->debug, "ss", "cod_alsa_device: {0}", msg);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_debug2(alsa_thread_t *self, const char *msg, const char *value)
{
    PyObject *res = PyObject_CallFunction(
	self->debug, "sss", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_debugi(alsa_thread_t *self, const char *msg, int value)
{
    PyObject *res = PyObject_CallFunction(
	self->debug, "ssi", "cod_alsa_device: {0}: {1}", msg, value);

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
    {/* LOCK SCOPE */
        BEGIN_LOCK(self);

        self->device_error = error;
        NOTIFY(self);

        END_LOCK(self);
    }
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
    int channels = 0;
    int bytes_per_sample = 0;
    int rate = 0;
    int big_endian = 0;
    snd_pcm_t *handle = NULL;
    pthread_attr_t thread_attr;
    struct sched_param sched;
    
    if (!PyArg_ParseTuple(args, "Osiiiiii:AlsaThread", 
                          &parent, &cardname, &start_without_device, &log_performance,
                          &channels, &bytes_per_sample, &rate, &big_endian)) 
        return NULL;
    
    if (bytes_per_sample != 2)
        return PyErr_Format(AlsaThreadError,
			    "only supports 2 bytes per sample, got %d",
			    bytes_per_sample);
    

    if (!(self = (alsa_thread_t *)PyObject_New(alsa_thread_t, &AlsaThreadType))) 
        return NULL;
    
    self->pcmtype = SND_PCM_STREAM_PLAYBACK;
    self->pcmmode = 0;
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

    self->channels = channels;
    self->rate = rate;
    self->big_endian = big_endian;

    /* These two get filled in when we set the format and
     * get to know what period really is.
     */
    self->period_frames = 0;
    self->swap_bytes = 0;
    
    self->thread = 0;
    
    pthread_mutex_init(&(self->mutex), NULL);
    pthread_cond_init(&(self->cond), NULL);

    self->handle = 0;
    self->device_error = NULL;
    self->log_message = NULL;
    self->log_param = NULL;

    /* Buffer is set up when we know the format */
    self->buffer_size = 0;
    self->play_pos = 0;
    self->play_size = 0;
    self->data_end = 0;
    self->data_size = 0;
    self->buffer = NULL;

    /* But we grab this right away with some assumptions about
     * what period size we might end up with */
    self->packets = calloc(sizeof(PyObject*), BUFFER_SECONDS * MAX_PERIODS_PER_SECOND);
    if (self->packets == NULL)
        return PyErr_NoMemory();


    /* Try to open card straight away */

    alsa_debug2(self, "opening card", self->cardname);
	
    Py_BEGIN_ALLOW_THREADS
    res = snd_pcm_open(&handle, self->cardname, self->pcmtype, self->pcmmode);
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
	    PyErr_Format(AlsaThreadError, "can't open %s: %s (%d)",
                         self->cardname, snd_strerror(res), res);
	    return NULL;
	}
    }
    else
    {
        if (thread_set_format(self, handle))
        {
            self->handle = handle;
            set_device_error(self, NULL);
        }
    }

    /* Propagate device error right away while we're in a Python context */
    if (self->device_error)
    {
        PyObject *set_device_error = get_parent_func(parent, "set_device_error");
        if (set_device_error == NULL)
            return NULL;    

        PyObject *res = PyObject_CallFunction(set_device_error, "s", self->device_error);

        Py_DECREF(set_device_error);

        if (res == NULL)
            return NULL;

        Py_DECREF(res);
    }

    /* Ready to kick off thread */

    /* Try to start with elevated priority (without going to extremes) */
    if (pthread_attr_init(&thread_attr) != 0)
        return PyErr_Format(AlsaThreadError, "pthread_attr_init: %s",
                            strerror(errno));

    if (pthread_attr_setinheritsched(&thread_attr,
                                     PTHREAD_EXPLICIT_SCHED) != 0)
        return PyErr_Format(AlsaThreadError, "pthread_attr_setinheritsched: %s",
                            strerror(errno));
        
    if (pthread_attr_setschedpolicy(&thread_attr, SCHED_RR) != 0)
        return PyErr_Format(AlsaThreadError, "pthread_attr_setschedpolicy: %s",
                            strerror(errno));
        
    sched.sched_priority = sched_get_priority_min(SCHED_RR);
    if (pthread_attr_setschedparam(&thread_attr, &sched) != 0)
        return PyErr_Format(AlsaThreadError, "pthread_attr_setschedparam: %s",
                            strerror(errno));
    
    if (pthread_create(&self->thread, &thread_attr, thread_main, self) != 0)
    {
        if (errno == EPERM)
        {
            alsa_log1(self, "couldn't start realtime thread, falling back on a normal thread");
            
            if (pthread_create(&self->thread, NULL, thread_main, self) != 0)
            {
                PyErr_Format(AlsaThreadError, "couldn't start thread (try 2): %s",
                             strerror(errno));
                return NULL;
            }
        }
        else
        {
            if (pthread_create(&self->thread, NULL, thread_main, self) != 0)
            {
                PyErr_Format(AlsaThreadError, "couldn't start thread: %s",
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
    // TODO: figure out how to do this safely with the thread running

    /*
    if (self->handle) {
        snd_pcm_drain(self->handle);
        snd_pcm_close(self->handle);
    }
    free(self->cardname);

    Py_XDECREF(self->log);
    Py_XDECREF(self->debug);

    PyObject_Del(self);
    */
}


static PyObject *
alsa_thread_buffer_empty(alsa_thread_t *self, PyObject *args) 
{
    int buffer_empty = 0;

    if (!PyArg_ParseTuple(args,":buffer_empty")) 
        return NULL;

    {
        Py_BEGIN_ALLOW_THREADS;
        BEGIN_LOCK(self);

        buffer_empty = (self->data_size == 0);

        END_LOCK(self);
        Py_END_ALLOW_THREADS;
    }

    return PyBool_FromLong(buffer_empty);
}
    

static Py_ssize_t playing_once(
    alsa_thread_t *self,
    PyObject *packet, const char *data, Py_ssize_t data_size,
    struct timespec *timeout,

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

        if (self->buffer_size <= 0)
        {
            /* Wait for thread to open the device */
            pthread_cond_timedwait(&self->cond, &self->mutex, timeout);
        }
            
        if (self->buffer_size > 0)
        {
            if (data != NULL)
            {
                if (self->data_size >= self->buffer_size)
                {
                    /* Wait for more room in buffer */
                    pthread_cond_timedwait(&self->cond, &self->mutex, timeout);
                }

                if (self->data_size < self->buffer_size)
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
                    
                    memcpy(self->buffer + self->data_end, data, stored);
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

                /* Wait for updates to playing_packet etc */
                pthread_cond_timedwait(&self->cond, &self->mutex, timeout);
            }
        }

        /* Bring the return parameters out of the lock and into Python land
         */

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
        self->log_param = NULL;;

        END_LOCK(self);
        Py_END_ALLOW_THREADS;
    }
    
    if (first_data_period >= 0)
    {
        /* Replace references to buffered packets with this one.
         *
         * BTW, this is only safe if only one Python thread is calling
         * this object.  However, two threads calling this would be
         * nonsense anyway, so let's not worry too much.
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
        *playing_packet = self->packets[play_period];
    }
    
    if (*playing_packet == NULL)
    {
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
    

static PyObject *alsa_thread_playing(alsa_thread_t *self, PyObject *args) 
{
    const char *data = NULL;
    Py_ssize_t data_size = 0;
    PyObject *packet = NULL;
    int stored = 0;
    PyObject *prev_playing_packet = NULL;
    PyObject *playing_packet = NULL;
    const char *prev_device_error = NULL;
    const char *device_error = NULL;
    struct timeval now;
    struct timespec timeout;
    
    /* Accept None or a string for the first argument */
    if (!PyArg_ParseTuple(args, "z#O:playing", &data, &data_size, &packet))
        return NULL;


    /* We'll keep running here as long as possible, and only return to
     * Python land when one (or more) of these things happen:
     *
     * - All data has been stored into the buffer
     * - The current packet being played has changed
     * - The device error has changed
     * - One second has passed
     */

    /* Never wait for more than one second, to avoid locking up
     * the calling thread (it controls skipping streams)
     */
    gettimeofday(&now, NULL);
    timeout.tv_sec = now.tv_sec + 1;
    timeout.tv_nsec = now.tv_usec * 1000;

    do
    {
        Py_ssize_t n;
        
        prev_playing_packet = playing_packet;
        prev_device_error = device_error;

        n = playing_once(self, packet, data, data_size, &timeout,
                                    &playing_packet, &device_error);

        if (data != NULL)
        {
            data += n;
            data_size -= n;
            stored += n;
        }
    }
    while ((data && data_size > 0)
           && (prev_playing_packet == NULL || prev_playing_packet == playing_packet)
           && (prev_device_error == NULL || prev_device_error == device_error));

    // TODO: remember device_error to avoid spawning new strings all the time

    return Py_BuildValue("iOs", stored, playing_packet, device_error);
}


static PyObject *alsa_thread_pause(alsa_thread_t *self, PyObject *args) 
{
    int res = 0;

    if (!PyArg_ParseTuple(args,":pause")) 
        return NULL;

    {
        Py_BEGIN_ALLOW_THREADS;
        BEGIN_LOCK(self);

        if (self->handle) {
            res = snd_pcm_pause(self->handle, 1);
        }

        END_LOCK(self);
        Py_END_ALLOW_THREADS;
    }
  
    if (res < 0) 
    {
        PyErr_SetString(AlsaThreadError,snd_strerror(res));
        return NULL;
    }

    return PyLong_FromLong(res);
}


static PyObject *alsa_thread_resume(alsa_thread_t *self, PyObject *args) 
{
    int res = 0;

    if (!PyArg_ParseTuple(args,":resume")) 
        return NULL;

    {
        Py_BEGIN_ALLOW_THREADS;
        BEGIN_LOCK(self);

        if (self->handle) {
            res = snd_pcm_pause(self->handle, 0);
        }

        END_LOCK(self);
        Py_END_ALLOW_THREADS;
    }

    if (res < 0) 
    {
        PyErr_SetString(AlsaThreadError,snd_strerror(res));
        return NULL;
    }

    return PyLong_FromLong(res);
}


static PyObject *
alsa_thread_discard_buffer(alsa_thread_t *self, PyObject *args) 
{
    if (!PyArg_ParseTuple(args,":discard_buffer")) 
        return NULL;

    {
        Py_BEGIN_ALLOW_THREADS;
        BEGIN_LOCK(self);

        /* Reset counters, keeping mind of that the player thread
         * might be trying to put data into the buffer right now.
         */
        if (self->buffer_size > 0)
        {
            self->data_end = (self->play_pos + self->play_size) % self->buffer_size;
            self->data_size = self->play_size;
        }

        /* Someone might be waiting on this */
        NOTIFY(self);

        END_LOCK(self);
        Py_END_ALLOW_THREADS;
    }
    

    Py_INCREF(Py_None);
    return Py_None;
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

    {
        BEGIN_LOCK(self);

        self->log_message = "player thread died";
        self->log_param = NULL;
        self->device_error = "player thread died";
        NOTIFY(self);
        
        END_LOCK(self);
    }

    return NULL;
}


static void thread_loop(alsa_thread_t *self)
{
    snd_pcm_t *handle;
    struct timeval start_data_wait;
    
    if (self->thread_perf_log) {
        gettimeofday(&start_data_wait, NULL);
    }

    while (1)
    {
        {
            BEGIN_LOCK(self);
            handle = self->handle;
            END_LOCK(self);
        }
        
        if (handle == NULL)
        {
            /* Attempt to reopen device */
            
            int res = snd_pcm_open(&handle, self->cardname,
                                   self->pcmtype, self->pcmmode);

            if (res >= 0) 
            {
                if (thread_set_format(self, handle))
                {
                    BEGIN_LOCK(self);

                    self->handle = handle;
                    self->log_message = "reopened device";
                    self->log_param = self->cardname;
                    self->device_error = NULL;

                    NOTIFY(self);

                    END_LOCK(self);

                    if (self->thread_perf_log) {
                        gettimeofday(&start_data_wait, NULL);
                    }
                }
                else
                {
                    struct timespec ts;

                    /* thread_set_format will have set the messages */
                    snd_pcm_close(handle);
                    handle = NULL;

                    /* Sleep to avoid busy-looping on a bad device */

                    ts.tv_sec = 3;
                    ts.tv_nsec = 0;
                    while (nanosleep(&ts, &ts) < 0 && errno == EINTR)
                    { }
                }
            }
            else
            {
                struct timespec ts;

                set_device_error(self, snd_strerror(res));

                /* Sleep before we try again */
                ts.tv_sec = 3;
                ts.tv_nsec = 0;
                while (nanosleep(&ts, &ts) < 0 && errno == EINTR)
                { }
            }
        }

        if (handle != NULL)
        {
            int data_size;
            unsigned char *data = NULL;

            {
                BEGIN_LOCK(self);
            
                if (self->data_size < self->period_size)
                {
                    pthread_cond_wait(&self->cond, &self->mutex);
                }
                
                if (self->data_size >= self->period_size)
                {
                    data = self->buffer + self->play_pos;
                    self->play_size = self->period_size;

                    data_size = self->data_size;
                }

                END_LOCK(self);
            }

            if (data != NULL)
            {
                int res = 0;
                struct timeval start_write;
                
                if (self->thread_perf_log)
                {
                    struct timeval now;
                    gettimeofday(&now, NULL);

                    fprintf(self->thread_perf_log, "%lu.%06lu %lu.%06lu data %d\n",
                            start_data_wait.tv_sec, start_data_wait.tv_usec,
                            now.tv_sec, now.tv_usec,
                            data_size);
                }

                if (self->swap_bytes)
                {
                    int i;
                    for (i = 0; i < self->period_size; i += 2)
                    {
                        unsigned char c = data[i];
                        data[i] = data[i + 1];
                        data[i + 1] = c;
                    }
                }
                        
                if (self->thread_perf_log)
                {
                    gettimeofday(&start_write, NULL);
                }

                /* Suddenly the size argument is frames, not bytes... */
                res = snd_pcm_writei(handle, data, self->period_frames);
                if (res == -EPIPE) 
                {
                    /* EPIPE means underrun */
                    res = snd_pcm_recover(handle, res, 1);
                    if (res >= 0)
                        res = snd_pcm_writei(handle, data, self->period_frames);
                }

                if (self->thread_perf_log && res > 0)
                {
                    struct timeval now;
                    gettimeofday(&now, NULL);

                    fprintf(self->thread_perf_log, "%lu.%06lu %lu.%06lu write\n",
                            start_write.tv_sec, start_write.tv_usec,
                            now.tv_sec, now.tv_usec);
                }


                {
                    BEGIN_LOCK(self);

                    /* No matter what, we are no longer trying to put
                     * any data into the device.
                     */
                    self->play_size = 0;
                    
                    if (res > 0)
                    {
                        self->play_pos = (self->play_pos + self->period_size) % self->buffer_size;
                        self->data_size -= self->period_size;
                    }
                    else if (res < 0)
                    {
                        self->handle = NULL;
                        self->log_message = "error writing to device";
                        self->log_param = snd_strerror(res);
                        self->device_error = snd_strerror(res);
                    }

                    NOTIFY(self);

                    END_LOCK(self);
                }

                if (res < 0)
                {
                    snd_pcm_close(handle);
                    handle = NULL;
                }
                else if (res == 0)
                {
                    // It seems we can get a 0 write when pausing, even in blocking mode?
                    printf("res == 0, sleeping 1 sec\n");
                    sleep(1);
                }

                if (self->thread_perf_log) {
                    gettimeofday(&start_data_wait, NULL);
                }
            }
        }
    }
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
            set_log_message(self, "error querying params", snd_strerror(res));
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
     * we can allocate the buffer (if we doesn't already have an OK
     * one.)
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


        {
            BEGIN_LOCK(self);

            if (self->buffer)
            {
                /* It's OK to discard anything in the buffer, since that
                 * is anyway now the wrong format.
                 */
                free(self->buffer);
                self->buffer = NULL;
            }
            
            self->buffer = malloc(buffer_size);

            // TODO: packets

            self->buffer_size = self->buffer ? buffer_size : 0;
            self->period_size = self->period_frames * self->channels * 2;
            self->play_pos = 0;
            self->data_end = 0;
            self->data_size = 0;
        
            /* Tell the Python thread about being ready to accept data */
            NOTIFY(self);

            END_LOCK(self);
        }
    }
    
    return 1;
}




/* AlsaThread Object Bureaucracy */

static PyMethodDef alsa_thread_methods[] = {
    { "buffer_empty", (PyCFunction)alsa_thread_buffer_empty, METH_VARARGS },
    { "pause", (PyCFunction)alsa_thread_pause, METH_VARARGS },
    { "resume", (PyCFunction)alsa_thread_resume, METH_VARARGS },
    { "playing", (PyCFunction)alsa_thread_playing, METH_VARARGS },
    { "discard_buffer", (PyCFunction)alsa_thread_discard_buffer, METH_VARARGS },
    {NULL, NULL}
};

#if PY_VERSION_HEX < 0x02020000 
static PyObject *	 
alsa_thread_getattr(alsa_thread_t *self, char *name) {	 
    return Py_FindMethod(alsa_thread_methods, (PyObject *)self, name);	 
}
#endif

static PyTypeObject AlsaThreadType = {
#if PY_MAJOR_VERSION < 3
    PyObject_HEAD_INIT(&PyType_Type)
    0,                              /* ob_size */
#else
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
#endif
    "alsaaudio.AlsaThread",                /* tp_name */
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

static PyMethodDef cod_alsa_device_methods[] = {
    { 0, 0 },
};


#if PY_MAJOR_VERSION >= 3

#define _EXPORT_INT(mod, name, value) \
  if (PyModule_AddIntConstant(mod, name, (long) value) == -1) return NULL;

static struct PyModuleDef cod_alsa_device_module = {
    PyModuleDef_HEAD_INIT,
    "cod_alsa_device",
    NULL,
    -1,
    cod_alsa_device_methods,
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
void initcod_alsa_device(void) 
#else
PyObject *PyInit_cod_alsa_device(void)
#endif
{
    PyObject *m;
    AlsaThreadType.tp_new = alsa_thread_new;

    PyEval_InitThreads();

#if PY_MAJOR_VERSION < 3
    m = Py_InitModule3("cod_alsa_device", cod_alsa_device_methods, "");
    if (!m) 
        return;
#else

    m = PyModule_Create(&cod_alsa_device_module);
    if (!m) 
        return NULL;

#endif

    AlsaThreadError = PyErr_NewException("cod_alsa_device.AlsaThreadError", NULL, 
                                        NULL);
    if (!AlsaThreadError)
#if PY_MAJOR_VERSION < 3
        return;
#else
        return NULL;
#endif

    /* Each call to PyModule_AddObject decrefs it; compensate: */

    Py_INCREF(&AlsaThreadType);
    PyModule_AddObject(m, "AlsaThread", (PyObject *)&AlsaThreadType);
  
    Py_INCREF(AlsaThreadError);
    PyModule_AddObject(m, "AlsaThreadError", AlsaThreadError);


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
