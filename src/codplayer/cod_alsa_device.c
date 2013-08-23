/* cod_alsa_device - ALSA device implementation, based on pyalsaaudio
 * but heavily modified.
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

#include "Python.h"
#if PY_MAJOR_VERSION < 3 && PY_MINOR_VERSION < 6
#include "stringobject.h"
#define PyUnicode_FromString PyString_FromString
#endif

#include <alsa/asoundlib.h>
#include <stdio.h>
#include <pthread.h>
#include <sched.h>


typedef struct {
    PyObject_HEAD;
    int pcmtype;
    int pcmmode;
    char *cardname;
  
    snd_pcm_t *handle;

    /* Parent device object methods */
    PyObject *log;
    PyObject *debug;
    PyObject *set_device_error;
    PyObject *set_current_packet;

    PyObject *format;
    int bytes_per_frame;
    int period_size;
    int swap_bytes;
} alsapcm_t;


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


/******************************************/
/* PCM object wrapper                   */
/******************************************/

static PyTypeObject ALSAPCMType;
static PyObject *ALSAAudioError;

static PyObject* get_parent_func(PyObject *parent, const char *attr)
{
    PyObject *func;

    func = PyObject_GetAttrString(parent, attr);
    if (func == NULL)
        return NULL;

    if (!PyCallable_Check(func))
    {
	Py_DECREF(func);
        return PyErr_Format(ALSAAudioError,
			    "parent.%s is not a callable function",
			    attr);
    }

    return func;
}


static int alsa_log1(alsapcm_t *self, const char *msg)
{
    PyObject *res = PyObject_CallFunction(
	self->log, "ss", "cod_alsa_device: {0}", msg);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_log2(alsapcm_t *self, const char *msg, const char *value)
{
    PyObject *res = PyObject_CallFunction(
	self->log, "sss", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int alsa_logi(alsapcm_t *self, const char *msg, int value)
{
    PyObject *res = PyObject_CallFunction(
	self->log, "ssi", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int alsa_debug1(alsapcm_t *self, const char *msg)
{
    PyObject *res = PyObject_CallFunction(
	self->debug, "ss", "cod_alsa_device: {0}", msg);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_debug2(alsapcm_t *self, const char *msg, const char *value)
{
    PyObject *res = PyObject_CallFunction(
	self->debug, "sss", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}

static int alsa_debugi(alsapcm_t *self, const char *msg, int value)
{
    PyObject *res = PyObject_CallFunction(
	self->debug, "ssi", "cod_alsa_device: {0}: {1}", msg, value);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}



static int set_current_packet(alsapcm_t *self, PyObject *packet)
{
    PyObject *res = PyObject_CallFunction(
	self->set_current_packet, "O", packet);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}


static int set_device_error(alsapcm_t *self, const char *error)
{
    PyObject *res = PyObject_CallFunction(
	self->set_device_error, "s", error);

    if (res == NULL)
	return 0;

    Py_DECREF(res);
    return 1;
}



static PyObject *
alsapcm_new(PyTypeObject *type, PyObject *args, PyObject *kwds) 
{
    int res;
    alsapcm_t *self;
    PyObject *parent = NULL;
    char *cardname = NULL;
    int start_without_device = 0;
    
    if (!PyArg_ParseTuple(args, "Osi:PCM", 
                          &parent, &cardname, &start_without_device)) 
        return NULL;
    
    if (!(self = (alsapcm_t *)PyObject_New(alsapcm_t, &ALSAPCMType))) 
        return NULL;
    
    self->handle = 0;
    self->pcmtype = SND_PCM_STREAM_PLAYBACK;
    self->pcmmode = 0;
    self->cardname = translate_cardname(cardname);

    /* Get the parent methods we need to do anything */
    self->log = get_parent_func(parent, "log");
    if (self->log == NULL)
        return NULL;    

    self->debug = get_parent_func(parent, "debug");
    if (self->debug == NULL)
        return NULL;    

    self->set_current_packet = get_parent_func(parent, "set_current_packet");
    if (self->set_current_packet == NULL)
        return NULL;    

    self->set_device_error = get_parent_func(parent, "set_device_error");
    if (self->set_device_error == NULL)
        return NULL;    

    self->format = NULL;
    self->bytes_per_frame = 0;
    self->period_size = 0;
    self->swap_bytes = 0;
    
    alsa_debug2(self, "opening card", self->cardname);
	
    Py_BEGIN_ALLOW_THREADS
    res = snd_pcm_open(&(self->handle), self->cardname, self->pcmtype,
                       self->pcmmode);
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
	    PyErr_Format(ALSAAudioError, "can't open %s: %s (%d)",
                         self->cardname, snd_strerror(res), res);
	    return NULL;
	}
    }
    else
    {
        set_device_error(self, NULL);
    }

    return (PyObject *)self;
}

static void alsapcm_dealloc(alsapcm_t *self) 
{
    if (self->handle) {
        snd_pcm_drain(self->handle);
        snd_pcm_close(self->handle);
    }
    free(self->cardname);

    Py_XDECREF(self->log);
    Py_XDECREF(self->debug);
    Py_XDECREF(self->set_current_packet);
    Py_XDECREF(self->set_device_error);

    Py_XDECREF(self->format);

    PyObject_Del(self);
}


static PyObject *
alsapcm_init_thread(alsapcm_t *self, PyObject *args) 
{
    int res;
    pthread_t this_thread;
    struct sched_param params;

    if (!PyArg_ParseTuple(args,":init_thread")) 
        return NULL;


    this_thread = pthread_self();

    /* Use a minimum priority round-robin RT thread - should be good
     * enough to get past everything else on a dedicated CD player
     * server.
     */
    params.sched_priority = sched_get_priority_min(SCHED_RR);

    res = pthread_setschedparam(this_thread, SCHED_RR, &params);
    if (res == 0)
    {
        /* Verify the change in thread priority */
        int policy = 0;
        res = pthread_getschedparam(this_thread, &policy, &params);
        if (res == 0)
        {
            if (policy == SCHED_RR)
            {
                alsa_logi(self, "realtime thread running at priority",
                          params.sched_priority);
            }
            else
            {
                alsa_logi(self, "thread not using expected scheduler, but this:",
                          policy);
            }
        }
        else
        {
            alsa_log1(self, "couldn't check if thread got realtime prio");
        }
    }
    else
    {
        alsa_log1(self, "error setting realtime scheduler, running at normal prio");
    }

    Py_INCREF(Py_None);
    return Py_None;
}
    

static PyObject *
alsapcm_dumpinfo(alsapcm_t *self, PyObject *args) 
{
    unsigned int val,val2;
    snd_pcm_format_t fmt;
    int dir;
    snd_pcm_uframes_t frames;
    snd_pcm_hw_params_t *hwparams;
    snd_pcm_hw_params_alloca(&hwparams);
    snd_pcm_hw_params_current(self->handle,hwparams);
    
    if (!PyArg_ParseTuple(args,":dumpinfo")) 
        return NULL;
    
    if (!self->handle) {
        PyErr_SetString(ALSAAudioError, "PCM device is closed");
        return NULL;
    }

    printf("PCM handle name = '%s'\n", snd_pcm_name(self->handle));
    printf("PCM state = %s\n", 
           snd_pcm_state_name(snd_pcm_state(self->handle)));
    
    snd_pcm_hw_params_get_access(hwparams, (snd_pcm_access_t *) &val);
    printf("access type = %s\n", snd_pcm_access_name((snd_pcm_access_t)val));

    snd_pcm_hw_params_get_format(hwparams, &fmt);
    printf("format = '%s' (%s)\n", 
           snd_pcm_format_name(fmt),
           snd_pcm_format_description(fmt));
    
    snd_pcm_hw_params_get_subformat(hwparams, (snd_pcm_subformat_t *)&val);
    printf("subformat = '%s' (%s)\n",
           snd_pcm_subformat_name((snd_pcm_subformat_t)val),
           snd_pcm_subformat_description((snd_pcm_subformat_t)val));
    
    snd_pcm_hw_params_get_channels(hwparams, &val);
    printf("channels = %d\n", val);

    snd_pcm_hw_params_get_rate(hwparams, &val, &dir);
    printf("rate = %d bps\n", val);

    snd_pcm_hw_params_get_period_time(hwparams, &val, &dir);
    printf("period time = %d us\n", val);

    snd_pcm_hw_params_get_period_size(hwparams, &frames, &dir);
    printf("period size = %d frames\n", (int)frames);

    snd_pcm_hw_params_get_buffer_time(hwparams, &val, &dir);
    printf("buffer time = %d us\n", val);

    snd_pcm_hw_params_get_buffer_size(hwparams, (snd_pcm_uframes_t *) &val);
    printf("buffer size = %d frames\n", val);

    snd_pcm_hw_params_get_periods(hwparams, &val, &dir);
    printf("periods per buffer = %d frames\n", val);

    snd_pcm_hw_params_get_rate_numden(hwparams, &val, &val2);
    printf("exact rate = %d/%d bps\n", val, val2);

    val = snd_pcm_hw_params_get_sbits(hwparams);
    printf("significant bits = %d\n", val);

    snd_pcm_hw_params_get_period_time(hwparams, &val, &dir);
    printf("period time = %d us\n", val);

    val = snd_pcm_hw_params_is_batch(hwparams);
    printf("is batch = %d\n", val);

    val = snd_pcm_hw_params_is_block_transfer(hwparams);
    printf("is block transfer = %d\n", val);

    val = snd_pcm_hw_params_is_double(hwparams);
    printf("is double = %d\n", val);

    val = snd_pcm_hw_params_is_half_duplex(hwparams);
    printf("is half duplex = %d\n", val);

    val = snd_pcm_hw_params_is_joint_duplex(hwparams);
    printf("is joint duplex = %d\n", val);

    val = snd_pcm_hw_params_can_overrange(hwparams);
    printf("can overrange = %d\n", val);

    val = snd_pcm_hw_params_can_mmap_sample_resolution(hwparams);
    printf("can mmap = %d\n", val);

    val = snd_pcm_hw_params_can_pause(hwparams);
    printf("can pause = %d\n", val);

    val = snd_pcm_hw_params_can_resume(hwparams);
    printf("can resume = %d\n", val);

    val = snd_pcm_hw_params_can_sync_start(hwparams);
    printf("can sync start = %d\n", val);

    Py_INCREF(Py_None);
    return Py_None;
}


static int set_format(alsapcm_t *self, PyObject *packet)
{
    int res,dir;
    unsigned int channels, set_channels;
    unsigned int rate, set_rate;
    snd_pcm_uframes_t period_size, set_period_size;
    snd_pcm_format_t sample_format, set_sample_format;
    unsigned int periods;
    snd_pcm_hw_params_t *hwparams;
    PyObject *format = NULL;

    format = PyObject_GetAttrString(packet, "format");

    if (format == NULL)
	return 0;

    /* Format hasn't changed  */
    if (format == self->format)
    {
        Py_DECREF(format);
        return 1;
    }

    // TODO: get this from format instead of being hardcoded...
    sample_format = SND_PCM_FORMAT_S16_BE;
    channels = 2;
    rate = 44100;
    period_size = 4096; // about 10 Hz
    periods = 4;
        
    self->swap_bytes = 0;
    self->bytes_per_frame = channels * 2;


    /* Change to this format. We keep track of the reference in self
       so any errors below doesn't have to decref.
    */
    Py_XDECREF(self->format);
    self->format = format;

    alsa_debug2(self, "setting format to", PyEval_GetFuncName(format));

    /* Allocate a hwparam structure on the stack, 
       and fill it with configuration space */
    snd_pcm_hw_params_alloca(&hwparams);

    while (1)
    {
        res = snd_pcm_hw_params_any(self->handle, hwparams);
        if (res < 0)
        {
            PyErr_Format(ALSAAudioError,
                         "error initialising hwparams: %s",
                         snd_strerror(res));
            return 0;
        }

        snd_pcm_hw_params_set_access(self->handle, hwparams, 
                                     SND_PCM_ACCESS_RW_INTERLEAVED);
        snd_pcm_hw_params_set_format(self->handle, hwparams, sample_format);
        snd_pcm_hw_params_set_channels(self->handle, hwparams, channels);

        dir = 0;
        snd_pcm_hw_params_set_rate(self->handle, hwparams, rate, dir);
        snd_pcm_hw_params_set_period_size(self->handle, hwparams, period_size, dir);
        snd_pcm_hw_params_set_periods(self->handle, hwparams, periods, 0);
    
        /* Write it to the device */
        res = snd_pcm_hw_params(self->handle, hwparams);
        if (res < 0)
        {
            PyErr_Format(ALSAAudioError,
                         "error setting hw params: %s",
                         snd_strerror(res));
            return 0;
        }

        
        /* Check if the card accepted our settings */
        res = snd_pcm_hw_params_current(self->handle, hwparams);
        if (res < 0)
        {
            PyErr_Format(ALSAAudioError,
                         "error querying params: %s",
                         snd_strerror(res));
            return 0;
        }

        snd_pcm_hw_params_get_format(hwparams, &set_sample_format);
        snd_pcm_hw_params_get_channels(hwparams, &set_channels);
        snd_pcm_hw_params_get_rate(hwparams, &set_rate, &dir);
        snd_pcm_hw_params_get_period_size(hwparams, &set_period_size, &dir); 
    
        if (channels != set_channels)
        {
            PyErr_Format(ALSAAudioError,
                         "couldn't set device to %d channels",
                         channels);
            return 0;
        }        

        if (rate != set_rate)
        {
            PyErr_Format(ALSAAudioError,
                         "couldn't set device to %d Hz",
                         rate);
            return 0;
        }        

        if (sample_format == set_sample_format)
        {
            /* Got an OK format */
            if (self->swap_bytes)
                alsa_debug1(self, "swapping bytes");

            break;
        }
        else
        {
            if (sample_format == SND_PCM_FORMAT_S16_BE)
            {
                alsa_debug1(self,
                            "SND_PCM_FORMAT_S16_BE didn't work, trying SND_PCM_FORMAT_S16_LE");

                /* Retry with little endian and swap bytes ourselves */
                sample_format = SND_PCM_FORMAT_S16_LE;
                self->swap_bytes = 1;
            }
            else
            {
                /* Give up */

                PyErr_Format(ALSAAudioError,
                             "couldn't set sample format to either "
                             "SND_PCM_FORMAT_S16_BE or SND_PCM_FORMAT_S16_LE");
                return 0;
            }
        }
    }

    /* Just use the period size determined by card */
    alsa_debugi(self, "using period size", set_period_size);
    self->period_size = set_period_size;
    
    return 1;
}


static PyObject *alsapcm_play_stream(alsapcm_t *self, PyObject *args) 
{
    PyObject *stream = NULL;
    int first_packet = 1;
    PyObject *packet = NULL;
    int period_bytes = 0;
    unsigned char *samples = NULL;
    int sample_len = 0;
    
    if (!PyArg_ParseTuple(args, "O:play_stream", &stream)) 
        return NULL;

    if (!PyIter_Check(stream))
    {
	Py_DECREF(stream);
        PyErr_SetString(ALSAAudioError, "stream is not an iterable object");
        return NULL;
    }

    while ((packet = PyIter_Next(stream)) != NULL)
    {
	int res;
        PyObject *data_object;
        char *data;
        Py_ssize_t data_len;
        
        /* When starting playing, set the packet directly as
	   the buffer is likely empty.
	*/
	if (first_packet)
	{
	    if (!set_current_packet(self, packet))
		goto loop_error;
	    first_packet = 0;
	}

        if (!self->handle)
        {
            int res;
                
            /* Try reopening the device */
            alsa_debug2(self, "retrying opening card", self->cardname);
    
            Py_BEGIN_ALLOW_THREADS;
            res = snd_pcm_open(&(self->handle), self->cardname, self->pcmtype,
                               self->pcmmode);
            Py_END_ALLOW_THREADS;
    
            if (res < 0) 
            {
                struct timespec ts;
                
                alsa_debug2(self, "error reopening card", snd_strerror(res));
                self->handle = 0;
                set_device_error(self, snd_strerror(res));

                /* Sacrifice this audio packet and retry in a couple of seconds */
                ts.tv_sec = 3;
                ts.tv_nsec = 0;
                while (nanosleep(&ts, &ts) < 0 && errno == EINTR)
                {
                }

                continue;
            }
            else
            {
                alsa_log2(self, "successfully reopened card", self->cardname);
                set_device_error(self, NULL);
            }
        }

	if (!set_format(self, packet))
	    goto loop_error;

        /* Set up the sample buffer now, if not already done for this format */
        if (period_bytes != self->period_size * self->bytes_per_frame)
        {
            if (samples) {
                free(samples);
                samples = NULL;
            }

            period_bytes = self->period_size * self->bytes_per_frame;

            if (period_bytes <= 0 || period_bytes >= 65536)
            {
                PyErr_Format(ALSAAudioError,
                             "weird period size: %d bytes",
                             period_bytes);
                goto loop_error;
            }

            samples = malloc(period_bytes);
            if (samples == NULL)
            {
                PyErr_NoMemory();
                goto loop_error;
            }

            sample_len = 0;
        }
            
        data_object = PyObject_GetAttrString(packet, "data");
        if (data_object == NULL)
            goto loop_error;
            
        if (PyString_AsStringAndSize(data_object, &data, &data_len) < 0)
            goto loop_error;
        
        /* Hold on to the reference to the data object through out
         * this code to ensure it isn't GCd under our feet.
         */

        /* Go into C land fully */
	Py_BEGIN_ALLOW_THREADS;

        res = 0;
        while (res >= 0 && data_len > 0)
        {
            // Copy into sample buffer
            int remaining = period_bytes - sample_len;
                
            if (data_len < remaining)
            {
                memcpy(samples + sample_len, data, data_len);
                sample_len += data_len;
                remaining -= data_len;
                data_len = 0;
            }
            else
            {
                memcpy(samples + sample_len, data, remaining);

                data += remaining;
                data_len -= remaining;
                remaining = 0;
                sample_len = period_bytes;
            }

            if (!remaining)
            {
                /* Full packet, so send it to the device */

                if (self->swap_bytes)
                {
                    int i;
                    for (i = 0; i < period_bytes; i += 2)
                    {
                        unsigned char c = samples[i];
                        samples[i] = samples[i + 1];
                        samples[i + 1] = c;
                    }
                }
            
                res = snd_pcm_writei(self->handle, samples, self->period_size);
                if (res == -EPIPE) 
                {
                    /* EPIPE means underrun */
                    res = snd_pcm_recover(self->handle, res, 1);
                    if (res >= 0)
                        res = snd_pcm_writei(self->handle, samples, self->period_size);
                }

                /* Start on new packet */
                sample_len = 0;
            }
        }

        Py_END_ALLOW_THREADS;
        
        Py_DECREF(data_object);
        
        /* When all that went into the device buffer, it's close
         * enough to this packet position to update the state.
         */
        if (!set_current_packet(self, packet))
            goto loop_error;

	Py_DECREF(packet);

	if (res < 0) 
	{
            alsa_log2(self, "error writing to card", snd_strerror(res));
            set_device_error(self, snd_strerror(res));

            /* Close device and drop format to prepare for reopen attempt */
            snd_pcm_close(self->handle);
            self->handle = 0;
            Py_XDECREF(self->format);
            self->format = NULL;
	}
    }

    if (PyErr_Occurred())
    {
        /* error getting iterator */
        return NULL;
    }

    /* Write any straggling data into the device */

    if (sample_len > 0)
    {
        int res;
        
        memset(samples + sample_len, 0, period_bytes - sample_len);

        if (self->swap_bytes)
        {
            int i;
            for (i = 0; i < period_bytes; i += 2)
            {
                unsigned char c = samples[i];
                samples[i] = samples[i + 1];
                samples[i + 1] = c;
            }
        }
            
        res = snd_pcm_writei(self->handle, samples, self->period_size);
        if (res == -EPIPE) 
        {
            /* EPIPE means underrun */
            res = snd_pcm_recover(self->handle, res, 1);
            if (res >= 0)
                res = snd_pcm_writei(self->handle, samples, self->period_size);
        }

	if (res < 0) 
	{
            alsa_log2(self, "error writing to card", snd_strerror(res));
            set_device_error(self, snd_strerror(res));

            /* Close device and drop format to prepare for reopen attempt */
            snd_pcm_close(self->handle);
            self->handle = 0;
            Py_XDECREF(self->format);
            self->format = NULL;
	}
    }

    if (samples) {
        free(samples);
        samples = NULL;
    }

    /* Loop finished on end of iterator */
    Py_INCREF(Py_None);
    return Py_None;

  loop_error:
    /* Exception already set when we get here. */
    Py_XDECREF(packet);

    if (samples) {
        free(samples);
        samples = NULL;
    }

    return NULL;
}


static PyObject *alsapcm_pause(alsapcm_t *self, PyObject *args) 
{
    int res;

    if (!PyArg_ParseTuple(args,":pause")) 
        return NULL;

    if (!self->handle) {
        PyErr_SetString(ALSAAudioError, "PCM device is closed");
        return NULL;
    }

    Py_BEGIN_ALLOW_THREADS
    res = snd_pcm_pause(self->handle, 1);
    Py_END_ALLOW_THREADS
  
    if (res < 0) 
    {
        PyErr_SetString(ALSAAudioError,snd_strerror(res));
        return NULL;
    }
    return PyLong_FromLong(res);
}


static PyObject *alsapcm_resume(alsapcm_t *self, PyObject *args) 
{
    int res;

    if (!PyArg_ParseTuple(args,":resume")) 
        return NULL;

    if (!self->handle) {
        PyErr_SetString(ALSAAudioError, "PCM device is closed");
        return NULL;
    }

    Py_BEGIN_ALLOW_THREADS
    res = snd_pcm_pause(self->handle, 0);
    Py_END_ALLOW_THREADS
  
    if (res < 0) 
    {
        PyErr_SetString(ALSAAudioError,snd_strerror(res));
        return NULL;
    }
    return PyLong_FromLong(res);
}



/* ALSA PCM Object Bureaucracy */

static PyMethodDef alsapcm_methods[] = {
    { "init_thread", (PyCFunction)alsapcm_init_thread, METH_VARARGS },
    { "dumpinfo", (PyCFunction)alsapcm_dumpinfo, METH_VARARGS },
    { "pause", (PyCFunction)alsapcm_pause, METH_VARARGS },
    { "resume", (PyCFunction)alsapcm_resume, METH_VARARGS },
    { "play_stream", (PyCFunction)alsapcm_play_stream, METH_VARARGS },

    {NULL, NULL}
};

#if PY_VERSION_HEX < 0x02020000 
static PyObject *	 
alsapcm_getattr(alsapcm_t *self, char *name) {	 
    return Py_FindMethod(alsapcm_methods, (PyObject *)self, name);	 
}
#endif

static PyTypeObject ALSAPCMType = {
#if PY_MAJOR_VERSION < 3
    PyObject_HEAD_INIT(&PyType_Type)
    0,                              /* ob_size */
#else
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
#endif
    "alsaaudio.PCM",                /* tp_name */
    sizeof(alsapcm_t),              /* tp_basicsize */
    0,                              /* tp_itemsize */
    /* methods */    
    (destructor) alsapcm_dealloc,   /* tp_dealloc */
    0,                              /* print */
#if PY_VERSION_HEX < 0x02020000
    (getattrfunc)alsapcm_getattr,   /* tp_getattr */
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
    "ALSA PCM device.",             /* tp_doc */
    0,					          /* tp_traverse */
    0,					          /* tp_clear */
    0,					          /* tp_richcompare */
    0,					          /* tp_weaklistoffset */
    0,					          /* tp_iter */
    0,					          /* tp_iternext */
    alsapcm_methods,		          /* tp_methods */
    0,			                  /* tp_members */
};



/******************************************/
/* Module initialization                  */
/******************************************/

static PyMethodDef alsaaudio_methods[] = {
    { 0, 0 },
};


#if PY_MAJOR_VERSION >= 3

#define _EXPORT_INT(mod, name, value) \
  if (PyModule_AddIntConstant(mod, name, (long) value) == -1) return NULL;

static struct PyModuleDef alsaaudio_module = {
    PyModuleDef_HEAD_INIT,
    "cod_alsa_device",
    NULL,
    -1,
    alsaaudio_methods,
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
    ALSAPCMType.tp_new = alsapcm_new;

    PyEval_InitThreads();

#if PY_MAJOR_VERSION < 3
    m = Py_InitModule3("cod_alsa_device", alsaaudio_methods, "");
    if (!m) 
        return;
#else

    m = PyModule_Create(&alsaaudio_module);
    if (!m) 
        return NULL;

#endif

    ALSAAudioError = PyErr_NewException("cod_alsa_device.ALSAAudioError", NULL, 
                                        NULL);
    if (!ALSAAudioError)
#if PY_MAJOR_VERSION < 3
        return;
#else
        return NULL;
#endif

    /* Each call to PyModule_AddObject decrefs it; compensate: */

    Py_INCREF(&ALSAPCMType);
    PyModule_AddObject(m, "PCM", (PyObject *)&ALSAPCMType);
  
    Py_INCREF(ALSAAudioError);
    PyModule_AddObject(m, "ALSAAudioError", ALSAAudioError);


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
