<%
source = data[0]['source']
disk_info = data[0]['disk_info']
os_info = data[0]['os_info']
subtitle = '##'
%>
# Disk ${source} characterization

It is a disk image of size ${disk_info["Size"]} and ${disk_info["npart"]} partitions.
* Model: ${disk_info.get("model", "")}
* SerialNumber: ${disk_info.get("serial_number", "")}

${subtitle} Partitions table

Partition|Size|Type|VSS
--|--|--|--
% for p in disk_info["partition"]:
${p["pnumber"]}|${p["size"]}|${p["type"]}|${p["vss"]}
% endfor

% for p in os_info:

${subtitle} Partition ${p[1:]} description
${subtitle}# OS Information

- **ProductName**: ${os_info[p].get("ProductName", 'Unknown')}
- **ComputerName**: ${os_info[p].get("ComputerName", 'Unknown')}
- **ProductId**: ${os_info[p].get("ProductId", 'Unknown')}
- **RegisteredOwner**: ${os_info[p].get("RegisteredOwner", 'Unknown')}
- **RegisteredOrganization**: ${os_info[p].get("RegisteredOrganization", 'Unknown')}
- **CurrentVersion**: ${os_info[p].get("CurrentVersion", 'Unknown')}
- **CurrentBuild**: ${os_info[p].get("CurrentBuild", 'Unknown')}
- **InstallationType**: ${os_info[p].get("InstallationType", 'Unknown')}
- **EditionID**: ${os_info[p].get("EditionID", 'Unknown')}
- **ProcessorArchitecture**: ${os_info[p].get("ProcessorArchitecture", 'Unknown')}
- **TimeZone**: ${os_info[p].get("TimeZone", 'Unknown')}
- **InstallDate**: ${os_info[p].get("InstallDate", 'Unknown')}
- **ShutdownTime**: ${os_info[p].get("ShutdownTime", 'Unknown')}

${subtitle}# Users

User|Creation date|Last login/logoff
--|--|--
% for u in os_info[p].get("users", []):
${u[0]}|${u[1]}|${u[2]}
% endfor

${subtitle}# User profiles
User|Creation date|Last login/logoff
--|--|--
% for u in os_info[p].get("user_profiles", []):
${u[0]}|${u[1]}|${u[2]}
% endfor


% endfor
