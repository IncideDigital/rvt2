## Template to show help about a section, job or module in markdown
<%!
# Notice the <%! : these lines are run at the beginning, without information about the data
# you can use this section in import modules and define new functions
import colorama
import sys

def multiline_value(value):
    if '\n' in value:
        return '\n    ```{}\n    ```'.format('\n'.join(map(lambda l: '    ' + l, value.split('\n'))))
    else:
        return '`{}`'.format(value)

def supports_color():
    plat = sys.platform
    supported_platform = plat != 'Pocket PC' and (plat != 'win32' or 'ANSICON' in os.environ)
    # isatty is not always implemented, #6223.
    is_a_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    return supported_platform and is_a_tty

def colorize_param(param):
    if supports_color():
        return '{}{}{}'.format(colorama.Fore.GREEN, param, colorama.Style.RESET_ALL)
    return '`{}`'.format(param)

def colorize_section(section):
    if supports_color():
        return '{}{}{}'.format(colorama.Style.BRIGHT, section, colorama.Style.RESET_ALL)
    return section

%>
<%
    # Notice the <% : these lines are run when data is available
    section = None
    job = None
    module = None
    if 'section' in data[0]:
        section = data[0]
    elif 'job' in data[0]:
        job = data[0]
    else:
        module = data[0]
%>\
% if section is not None:
<%doc>

Template for a section

</%doc>\
${colorize_section("# Section " + section['section'])}

${section['description']}

${colorize_section('## Jobs')}

% for job in section['jobs']:
- `${colorize_param(job['job'])}`: ${job['short']}
% endfor
% elif job is not None:
<%doc>

Template for a job

</%doc>\
${colorize_section("# Job `{}`".format(job['job']))}

${job['description']}
% if job.get('params', {}):

${colorize_section('## Configurable parameters')}

% if 'path' in job['params_help'] and not 'path' in job.get('params', {}):
- ${colorize_param('path')}: ${job['params_help']['path']} | ${colorize_section('Default')}: `${job['params'].get('path', '')}`
% endif
% for param in job.get('params', {}).keys():
- ${colorize_param(param)}: ${job['params_help'].get(param, '')} | ${colorize_section('Default')}: `${job['params'][param]}`
% endfor
% endif
% if job.get('other_vars', []):

${colorize_section('## Context')}

% for other_var in job.get('other_vars', {}):
- ${colorize_param(other_var['var'])}: ${multiline_value(other_var['value'])}
% endfor
% elif job is not None:
<%doc>

Template for a module

</%doc>\
${colorize_section('# Module `{}`'.format(module['module']))}

${module['description']}
% endif
% else:
${colorize_section('`{}` not found. No package defined for this section, job or module.'.format(module['module']))}
% endif
