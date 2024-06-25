<%
source = data[0]['source']
disk_info = data[0]['disk_info']
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
