#!/usr/bin/env python3

# Find Open OnDemand logs, parse them, and send them via POST request to the
# endpoint run by the ACCESS Monitoring and Measurement (ACCESS MMS) team who
# will ingest and aggregate the data to be included in ACCESS XDMoD.

import configparser
import subprocess

# If true, print debugging statements as it runs.
DEBUG = True

# Name of the configuration file in which metadata about the logs and the runs
# of this script are read/written. Assumed to be in the same directory as this
# script.
CONF_FILENAME = 'conf.ini'

def __run_pipeline(*args):
    """
        Run a pipeline of shell commands in subprocesses. Errors are piped to
        /dev/null except for the last command in the pipeline.

        Parameters
        ----------
        args : tuple of tuples of strings
            Each of the inner tuples contains the arguments to a command.
            Each of the outer tuples are commands that are piped together in
            order.

        Returns
        -------
        dict
            Keys 'stdout' and 'stderr' contain the string results of running
            the last command in the pipeline, or None if that stream is empty.
            Key 'code' contains the exit status code of the last command in
            the pipeline.
    """
    if DEBUG:
        print(
            'Running command `'
            + ' | '.join([
                ' '.join([
                    arg for arg in process_args
                ]) for process_args in args
            ])
            + '`'
        )
    # Start with no process being run yet.
    old_process = None
    # For each process in the pipeline,
    for process_args in args:
        # Run the next process.
        new_process = subprocess.Popen(
            process_args,
            stdin=None if old_process is None else old_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        # Prepare to run the process after that.
        old_process = new_process
    # Prepare to return the results.
    results = {}
    # Get the stdout and stderr bytes from the last process that ran.
    results['stdout'], results['stderr'] = old_process.communicate()
    # For both stdout and stderr,
    for stream in results:
        # If the stream is not empty,
        if results[stream]:
            # Turn the stream's bytes into text and strip out the newline at
            # the end.
            results[stream] = results[stream].decode('utf-8').rstrip()
    # Get the exit code from the last process that ran.
    results['code'] = old_process.returncode
    # Return the results.
    return results

def __find_conf_value(conf, key, pipeline_args, default):
    """
        Run a pipeline of commands to determine a particular configuration
        value. If that fails, get the value from this script's configuration
        file. If that fails, use a provided default value.

        Parameters
        ----------
        conf : configparser.ConfigParser 
            The parser for this script's configuration file.
        key : string
            The name of the configuration value we are trying to find.
        pipeline_args : tuple of tuples of strings
            Each of the inner tuples contains the arguments to a command.
            Each of the outer tuples are commands that are piped together in
            order.
        default : string
            The default value to use if the value cannot otherwise be found.

        Returns
        -------
        string
            The value to use.
    """
    if DEBUG:
        print('Finding conf value of ' + key)
    # Run the pipeline to try to find the value.
    pipeline_results = __run_pipeline(*pipeline_args)
    # If the pipeline successfully found the value,
    if pipeline_results['code'] == 0:
        # Use that value.
        value = pipeline_results['stdout']
        if DEBUG:
            print('Got value of ' + key + ' programmatically: ' + value)
    # If the pipeline did not successfully find the value,
    else:
        # Read this script's configuration file to see if a previous value is
        # recorded.
        value = conf.get('main', key)
        if value and DEBUG:
            print(
                'Got value of ' + key + ' from ' + CONF_FILENAME + ': '
                + value
            )
        # If no previous value was recorded,
        else:
            # Use the provided default value.
            value = default
            if DEBUG:
                print('Using default value for ' + key + ': ' + value)
    # Record the value to be written back to this script's configuration file.
    conf.set('main', key, value)
    # Return the value.
    return value

# Read this script's configuration file.
conf = configparser.ConfigParser(allow_no_value=True)
parsed_filenames = conf.read(CONF_FILENAME)
# If the configuration file cannot be read, raise an exception.
if not parsed_filenames:
    raise FileNotFoundError(CONF_FILENAME + ' not found.')
# Read the required sections from the configuration file.
try:
    logs_section = conf['logs']
    runs_section = conf['runs']
# If any section was not found, raise an exception.
except KeyError:
    raise KeyError('Missing required section in ' + CONF_FILENAME)

# Find the path to the main Apache configuration file by querying the HTTP
# daemon or otherwise falling back to this script's configuration file or a
# default value.
apache_conf_path = __find_conf_value(
    conf,
    key='apache_conf_path',
    command_args=(
        ('httpd', '-t', '-D', 'DUMP_INCLUDES',),
        ('grep', '^\s*(\*)',),
        ('awk', '{print $2}'),
    ),
    default='/etc/httpd/conf/httpd.conf',
)

# Find the path to the Open OnDemand portal configuration file by querying the
# HTTP daemon or otherwise falling back to this script's configuration file or
# a default value.
ood_portal_conf_path = __find_conf_value(
    conf,
    key='ood_portal_conf_path',
    command_args=(
        ('httpd', '-t', '-D', 'DUMP_INCLUDES',),
        ('grep', 'ood-portal.conf',),
        ('awk', '{print $2}'),
    ),
    default='/etc/httpd/conf.d/ood-portal.conf',
)

# Look for the file name of the Open OnDemand access logs by parsing the Open
# OnDemand portal configuration or otherwise falling back to this script's
# configuration file or a default value.
access_log_filename = __find_conf_value(
    conf,
    key='access_log_filename',
    command_args=(
        ('grep', '^\s*[^#]\s*\<CustomLog\>', ood_portal_conf_path,),
        ('grep', '_access_',),
        ('awk', '{print $2}',),
        ('cut', '-d', '"', '-f', '2',),
    ),
    default='/etc/httpd/conf.d/ood-portal.conf',
)

#custom_log = __run_pipeline(
#    ('grep', '\<CustomLog\>', ood_portal_conf_path,),
#    ('awk', '{print $3}',),
#)
#
#if DEBUG:
#    print('CustomLog:' + custom_log)
#
#log_format = __run_pipeline(
#    ('grep', '\<LogFormat\>', apache_conf_path,),
#    ('grep', '\<' + custom_log + '\>',),
#    ('sed', 's/\\\\\\"/\'/g',),
#    ('cut', '-d', '"', '-f', '2',),
#    ('sed', 's/\'/"/g',),
#)
#
#if DEBUG:
#    print('LogFormat:' + log_format)

# Write the configuration values back to the configuration file.
comment_header = """\
# This is a configuration file used by post_ood_logs_to_access_mms.py.
# The values will be written/overwritten in-place in this file when the script
# runs and then used in future runs of the script if the script is otherwise
# unable to determine the log metadata values by parsing the Apache
# configuration.
"""
with open(CONF_FILENAME, 'w') as conf_file:
    conf_file.write(comment_header)
with open(CONF_FILENAME, 'a') as conf_file:
    conf.write(conf_file)
