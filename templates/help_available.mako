## Template to show help about the available jobs in markdown
<%!
# Notice the <%! : these lines are run at the beginning, without information about the data
# you can use this section in import modules and define new functions
import colorama
import sys

def supports_color():
    plat = sys.platform
    supported_platform = plat != 'Pocket PC' and (plat != 'win32' or 'ANSICON' in os.environ)
    # isatty is not always implemented, #6223.
    is_a_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    return supported_platform and is_a_tty

def colorize_job(job):
    if supports_color():
        return '{}{}{}'.format(colorama.Fore.GREEN, job, colorama.Style.RESET_ALL)
    return job

def colorize_section(section):
    if supports_color():
        return '{}{}{}'.format(colorama.Style.BRIGHT, section, colorama.Style.RESET_ALL)
    return section

%>\
<%
# Notice the <% : these lines are run when data is available
sections = {}
for job in data:
    job_section = job.get('section', None)
    if not job_section:
        job_section = 'unclassified'
    if job_section in sections:
        sections[job_section].append(job)
    else:
        sections[job_section] = [job]
%>\
% for section in sorted(sections.keys()):
${colorize_section('# Section ' + section)}

% for job in sections[section]:
- ${colorize_job(job['job'])}: ${job.get('short', '')}
% endfor

% endfor
