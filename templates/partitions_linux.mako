<%
source = data[0]['source']
partitions = data[0]['partitions']
subtitle = '##'
%>

${subtitle}# Filesystem table

Device|Mount Point|File System Type|Options|Backup Operation|File System Check Order
--|--|--|--|--|--
% for u, partition in partitions.items():
${partition['device']}|${partition['mount_point']}|${partition['type']}|${partition['options']}|${partition['backup']}|${partition['pass']}
% endfor
