<%
source = data[0]['source']
os_info = data[0]['os_info']
subtitle = '##'
%>
# Source ${source} OS LINUX characterization

% for p in os_info:

${subtitle} Partition ${p[1:]} description
${subtitle}# OS Information

|Information|Value|
--|--
**ProductName**| ${os_info[p].get("ProductName", 'Unknown')}
**ComputerName**| ${os_info[p].get("ComputerName", 'Unknown')}
**DistributionRelease**| ${os_info[p].get("CurrentVersion", 'Unknown')}
**DistribCodename**| ${os_info[p].get("DistribCodename", 'Unknown')}
**LinuxKernelVersion**| ${os_info[p].get("LinuxKernelVersion", 'Unknown')}
**TimeZone**| ${os_info[p].get("TimeZone", 'Unknown')}
**OSInstallDate**| ${os_info[p].get("InstallDate", 'Unknown')}
**ShutdownTime**| ${os_info[p].get("ShutdownTime", 'Unknown')}
**IpAddress**| ${os_info[p].get("IpAddress", '-')}

% endfor
