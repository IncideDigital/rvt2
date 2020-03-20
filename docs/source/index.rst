.. rvt2 documentation master file, created by
   sphinx-quickstart on Thu Aug  1 14:31:34 2019.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to rvt2's documentation!
================================

Revealer Toolkit 2 (RVT2) is a framework for computer forensics. It is written
in Python 3 and internally many open source tools like *The Sleuth Kit* or
*regripper*.

RVT2 aims to automate rutinary tasks and analysis when managing forensic
images, or *sources*. RVT2 is specially useful in an environment with many
*cases* and many *sources*.

RVT2 is developed and continously used at INCIDE, a Spanish DFIR company sited
at the beautiful city of Barcelona (see http://www.incide.es)
for more details), and is designed to work on Debian stable version, althought
it is possible to adapt it to other other linux flavours.

This is the documentation for developers of the rvt2. You can find the
docs for the users of the RVT at https://incidedigital.github.io/rvt2-docs/.

Coding style
============

The source code must be linted using flake8
http://flake8.pycqa.org/en/latest/, but we prefer ignoring messages E501
(line too long) and W293 (blank line contains whitespace, many text editors
don't have this option). This rules are defined in the file ``.flake8rc``, in
the root of the project.

Comments must be in in Google Style Python Docstring
(https://www.sphinx-doc.org/en/1.5/ext/example_google.html) in English, with
these additional styles:

- The options that can be set in the ``.cfg`` files MUST be described in a section named *Configuration* at the module class docstring.

Example::

    Get data from from_module, set or update some if its fields and yield again.

    Configuration:
        - **presets**: A dictionary of fields to be set, unless already set by data yielded by from_module.
        - **fields**: A dictionary of fields to be set. `fields` will be managed as a string template, passing the data yielded by from_module as parameter.

The default behaviour of the log messages is as follows. You can change this
default behaviour in the configuration files.

- DEBUG: messages to assist while debugging but not the normal use. These
  messages won't be included in the logfiles, but they will be shown on screen if
  the rvt2 is run with the ``-v`` parameter. 
- INFO: messages to assist the normal use. The messages will be included in the
  logfiles, and they won't be shown on screen unless the ``-v`` parameter is used.
- WARNING: the module found an error or thinks something funny happened, but the
  execution will continue. These messages are included in the logfiles as well
  as shown on the screen.
- ERROR: the module found an error and it can't continue the execution. The
  current job will stop, but the rest of scheduled jobs will try to run unless
  the ``stop_on_error`` flag is set. These messages are included in the
  logfiles as well as shown on the screen.
- CRITICAL: the rvt found an error and the execution won't continue. These
  messages are included in the logfiles as well as shown on the screen.

.. toctree::
   :maxdepth: 4
   :caption: Contents:

   base
   plugins
   rvt2


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
