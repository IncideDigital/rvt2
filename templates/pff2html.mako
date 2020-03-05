<!DOCTYPE html>
<HTML><!--  -->
<HEAD>
	<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1" />
	<title>
		${subject}
	</title>
    <style>
        table {
            border-collapse: separate;
            font-family:sans-serif; font-size:small;
            border-spacing: 0;
        }
        .bordered {
            border: solid #ccc 1px;
            -moz-border-radius: 6px;
            -webkit-border-radius: 6px;
            border-radius: 6px;
            -webkit-box-shadow: 0 1px 1px #ccc;
            -moz-box-shadow: 0 1px 1px #ccc;
            box-shadow: 0 1px 1px #ccc;
        }
        .bordered tr:hover {
            background: #ECECEC;    
            -webkit-transition: all 0.1s ease-in-out;
            -moz-transition: all 0.1s ease-in-out;
            transition: all 0.1s ease-in-out;
        }
        .bordered td, .bordered th {
            border-left: 1px solid #ccc;
            border-top: 1px solid #ccc;
            padding: 5px;
        }
        .bordered th {
            background-color: #ECECEC;
            background-image: -webkit-gradient(linear, left top, left bottom, from(#E8E8E8), to(#909090));
            background-image: -webkit-linear-gradient(top, #E8E8E8, #909090);
            background-image: -moz-linear-gradient(top, #E8E8E8, #909090);    
            background-image: linear-gradient(top, #E8E8E8, #909090);
            -webkit-box-shadow: 0 1px 0 rgba(255,255,255,.8) inset;
            -moz-box-shadow:0 1px 0 rgba(255,255,255,.8) inset;
            box-shadow: 0 1px 0 rgba(255,255,255,.8) inset;
            border-top: none;
            text-shadow: 0 1px 0 rgba(255,255,255,.5);
        }
        .bordered td:first-child, .bordered th:first-child {
            border-left: none;out_headers
        }
        .bordered th:first-child {
            -moz-border-radius: 6px 0 0 0;
            -webkit-border-radius: 6px 0 0 0;
            border-radius: 6px 0 0 0;
        }
        .bordered th:last-child {
            -moz-border-radius: 0 6px 0 0;
            -webkit-border-radius: 0 6px 0 0;
            border-radius: 0 6px 0 0;
        }
        .bordered td:first-child{
            text-align: left;
        }
        tr:nth-child(2n+1) { background:#ECECEC; }
        .bordered th:only-child{
            -moz-border-radius: 6px 6px 0 0;
            -webkit-border-radius: 6px 6px 0 0;
            border-radius: 6px 6px 0 0;
        }
        .bordered tr:last-child td:first-child {
            -moz-border-radius: 0 0 0 6px;
            -webkit-border-radius: 0 0 0 6px;
            border-radius: 0 0 0 6px;
        }
        .bordered tr:last-child td:last-child {
            -moz-border-radius: 0 0 6px 0;
            -webkit-border-radius: 0 0 6px 0;
            border-radius: 0 0 6px 0;
        }
        pre {
            white-space: pre-wrap;
            white-space: -moz-pre-wrap;
            white-space: -pre-wrap;
            white-space: -o-pre-wrap;
            word-wrap: break-word;
        }${extra_style}
    </style>
	<script type="text/javascript">
		<!--
		function sizeTbl(h) {
		  var tbl = document.getElementById('tbl');
		  tbl.style.display = h;
		}
		function doKey($k) {
			if ( (($k>64) && ($k<91))   ||   (($k>96) && ($k<123)) ) {
				var tbl = document.getElementById('tbl');
				tbl.style.display = 'block';
			}
		}
		// -->
	</script> 
</HEAD>
<BODY onKeyPress="doKey(window.event.keyCode)">
	<TABLE class="bordered">
		<tr><td><b>Item</b></td><td>e-mail item (${tipe}) - <a href="javascript:sizeTbl('block')">Metadata</a></td></tr>
		<tr><td><b>Source</b></td><td>${source}</td></tr>
% for i in campos:
% if i[1] != "":
        <tr><td><b>${i[0]}</b></td><td>${i[1]}</td></tr>
% endif
% endfor
% if tos != "":
        <tr><td><b>To</b></td><td>${tos}</td></tr>
% endif
% if ccs != "":
        <tr><td><b>CC</b></td><td>${ccs}</td></tr>
% endif
% if bccs != "":
       <tr><td><b>BCC</b></td><td>${bcc}</td></tr>
% endif
% if attach_info == "si":
% for att in attach:
        <tr><td><b>Attachment</b></td><td><a href="${att[0]}" target="_blank">${att[0].split("/")[1]}</a> (${att[1]} bytes)</td></tr>
% endfor
% endif
	</TABLE><br>
% if pretable != "":
${pretable}
% endif
<DIV id=tbl style="overflow:hidden;display:none">
<TABLE class="bordered" style="font-size: medium;">
<TR><TD><a href="javascript:sizeTbl('none')">[X]</a> <b>METADATA:</b><br><br>
% if out_headers:
<b>${out_headers[0]}</b>
<pre>
${out_headers[1]}
</pre>
% endif

% if int_headers:
<b>Internet headers:</b>
<pre>
${int_headers}
</pre>
% endif

% if recipientes:
<b>Recipients:</b>
<pre>
${recipientes}
</pre>
% endif

% if conv_ind:
<b>Conversation index:</b>
<pre>
${conv_ind}
</pre>
% endif

% if attach_info == "si":
<b>Attachment information:</b>
<pre>
% for att in attach:
Attachment: ${att[0]} (${att[1]} bytes)
% endfor
</pre>
% endif
% if R_out_head:
<b>${R_out_head[0]}</b>
<pre>
${R_out_head[1]}
</pre>
% endif
<!--inicio del body-->
</TD></TR>
</TABLE>
</DIV><br><br>
${body}
</BODY>
</HTML>
