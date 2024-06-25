<!DOCTYPE html>
<html>
    <head>
        <meta charset="utf-8">
        <title>WhatsApp chat</title>
        <link rel="stylesheet" type="text/css" href="//fonts.googleapis.com/css?family=Open+Sans" />
        <style>
        /* Left and right positions */
        .left-sent {
          float: left;
          text-align: left;
          width: 80%;
        }

        .right-sent {
          float: right;
          text-align: right;
          width: 20%;
        }

        .left-received {
          float: left;
          text-align: left;
          width: 20%;
        }

        .right-received {
          float: right;
          text-align: right;
          width: 80%;
        }

        /* Chat containers */
        .message {
        border: 2px solid #dedede;
        background-color: #f1f1f1;
        border-radius: 5px;
        margin: 10px 0;
        padding: 1em 1em 1em 1em;
        }
        /* Message text container */
        .message-body {
          display: inline-block;
          vertical-align: middle;
          line-height: 2em;
          text-align: left;
        }
        /* Received and sent chat container */
        .received {
          border-color: #007780;
          background-color: #27bae166;
          transform: translate(0%, 0%);
          width: 70%;
        }

        .sent {
          border-color: #005419;
          background-color: #9cfb6ab3;
          transform: translate(30%, 0%);
          width: 70%;
        }

	/* Quote boxes */
        .sent-quote {
          border-color: #007780;
          background-color: #3cb37150;
          transform: translate(0%, 0%);
          width: 100%;
        }

        .received-quote {
          border-color: #007780;
          background-color: #00008b20;
          transform: translate(0%, 0%);
          width: 100%;
        }

        /* Clear floats */
        .message::after {
          content: "";
          clear: both;
          display: table;
        }

        /* Style author text */
        .author-right {
          color: #000;
          margin-bottom: 0.4em;
        }

        /* Style author text */
        .author-left {
          color: #000;
          margin-bottom: 0.4em;
        }

        /* Style time text */
        .time-right {
          float: right;
          color: #000;
        }

        /* Style time text */
        .time-left {
          float: left;
          color: #000;
        }

        h1 {
        	font-family: Open Sans;
        	font-size: 24px;
        	font-style: normal;
        	font-variant: normal;
        	font-weight: 500;
        	line-height: 26.4px;
        }
        h3 {
        	font-family: Open Sans;
        	font-size: 14px;
        	font-style: normal;
        	font-variant: normal;
        	font-weight: 500;
        	line-height: 15.4px;
        }
        p {
        	font-family: Open Sans;
        	font-size: 14px;
        	font-style: normal;
        	font-variant: normal;
        	font-weight: 400;
        	line-height: 20px;
        }
        blockquote {
        	font-family: Open Sans;
        	font-size: 14px;
        	font-style: normal;
        	font-variant: normal;
        	font-weight: 400;
        	line-height: 10px;
		border-left: 4px solid #09C;
		padding-left: 8px
        }
        pre {
        	font-family: Open Sans;
        	font-size: 13px;
        	font-style: normal;
        	font-variant: normal;
        	font-weight: 400;
        	line-height: 18.5667px;
        }
        img {
          /* width: "pixels"; */
          width: auto;
          height : auto;
          max-width: 100%;
          max-height: 95%;
        }

        .font {
          font-family: Open Sans;
          font-size: 14px;
          font-style: normal;
          font-variant: normal;
          font-weight: 400;
          line-height: 20px;
        }
        </style>

    </head>
    <body>
        % for r in data:
          % if r["message_type"] != "Key change":
	        <%
	          r["message"] = r["message"].replace("\\n", "<br />")
	          r["quote"] = r["quote"].replace("\\n", "<br />")
          %>
            % if r["is_from_me"] != "1":
	          ## received message
              <div class="message received font">
                <div class="left-received">
                  <div class="author-left">${r["message_from"]}</div>
                  % if r["date_sent"] is not None:
                  <div class="time-left">${r["date_creation"]}</div>
                  % endif
                </div>
                <div class="right-received">
                  % if r["message_type"] == "Text message":
		                % if r["quote"] == "":
                      <div class="message-body">${r["message"]}</div>
		                % else:
                      <div class="received-quote">
                        <blockquote class="message-body" style="color:#006400;">${r["quote"]}</blockquote>
                      </div>
                      <div class="message-body">${r["message"]}</div>
		                % endif
                  % elif r["message_type"] == "Image":
                    <div class="message-body"><img src="${r["message_media_location"]}">${r["message_media_title"]}</div>
                  % elif r["message_type"] in ["Video", "Voice/Audio note"]:
                    <div class="message-body"><a href="${r["message_media_location"]}">${r["message_media_location"]}</a></div>
                  % elif r["message_type"] == "Contact":
                    <div class="message-body">${r["message"]}: ${r["contact"]}</div>
                  % elif r["message_type"] == "Location":
                    <div class="message-body">${r["message"]}: ${r["lon_lat"]}; ${r["contact"]}</div>
                  % elif r["message_type"] == "Url":
                    <% url = 'http' + r["message"].split('http')[-1] %>
                    <% url_title = r["message"].split('http')[0] %>
                    <div class="message-body">${url_title}<a href="${url}">${url}</a></div>
                  % elif r["message_type"] == "Document":
                    <div class="message-body"><a href="${r["message_media_location"]}">${r["message"]}</a></div>
                  % elif r["message_type"] == "Deleted":
                    <div class="message-body">This message has been deleted</div>
                  % endif
                </div>
              </div>
            % else:
            ## sent message
              <div class="message sent font">
                <div class="right-sent">
                  <div class="author-right">${r["message_from"]}</div>
                  % if r["date_sent"] is not None:
                  <div class="time-right">${r["date_sent"]}</div>
                  % endif
                </div>
                <div class="left-sent">
                  % if r["message_type"] == "Text message":
                    % if r["quote"] == "":
                      <div class="message-body">${r["message"]}</div>
                    % else:
		      <div class="sent-quote">
                      	<blockquote class="message-body" style="color:#0000cd;">${r["quote"]}</blockquote>
		      </div>
		      <div class="message-body">${r["message"]}</div>
                    % endif
		              % elif r["message_type"] == "Image":
                    <div class="message-body"><img src="${r["message_media_location"]}">${r["message_media_title"]}</div>
                  % elif r["message_type"] in ["Video", "Voice/Audio note"]:
                    <div class="message-body"><a href="${r["message_media_location"]}">${r["message_media_location"]}</a></div>
                  % elif r["message_type"] == "Contact":
                    <div class="message-body">${r["message"]}: ${r["contact"]}</div>
                  % elif r["message_type"] == "Location":
                    <div class="message-body">${r["message"]}: ${r["lon_lat"]}; ${r["contact"]}</div>
                  % elif r["message_type"] == "Url":
                    <% url = 'http' + r["message"].split('http')[-1] %>
                    <% url_title = r["message"].split('http')[0] %>
                    <div class="message-body">${url_title}<a href="${url}">${url}</a></div>
                  % elif r["message_type"] == "Document":
                    <div class="message-body"><a href="${r["message_media_location"]}">${r["message"]}</a></div>
                  % elif r["message_type"] == "Deleted":
                    <div class="message-body">This message has been deleted</div>
                  % endif
                </div>
              </div>
            % endif
          %endif
        % endfor
    </body>
</html>
