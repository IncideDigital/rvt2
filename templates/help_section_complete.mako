## Template to show complete help about a section in markdown
<%!
# Notice the <%! : these lines are run at the beginning, without information about the data
# you can use this section in import modules and define new functions
import sys

def multiline_value(value):
    if '\n' in value:
        return '\n    ```{}\n    ```'.format('\n'.join(map(lambda l: '    ' + l, value.split('\n'))))
    else:
        return '`{}`'.format(value)

def supports_color():
    # this template does not use colorization. Setting this to false is easy and keeps compatibility with help.mako
    return False

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
    section = data[0]
%>\
${colorize_section("# Section " + section['section'])}

${section['description']}

${colorize_section('## Jobs')}

% for job in section['jobs']:
- `${colorize_param(job['job'])}`: ${job['short']}
% endfor

% for job in section['jobs']:
${colorize_section("### Job `{}`".format(job['job']))}

${job['description']}
% if job.get('params', {}):

${colorize_section('#### Configurable parameters')}

|Parameter|Description|Default|
|--|--|--|
% if 'path' in job['params_help'] and not 'path' in job.get('params', {}):
|`path`|${job['params_help']['path']}|`${job['params'].get('path', '')}`|
% endif
% for param in job.get('params', {}).keys():
|`${param}`|${job['params_help'].get(param, '')}|`${job['params'][param]}`|
% endfor
% endif

% endfor
