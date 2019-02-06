from flask import Flask, request, Response, jsonify
import os
import requests
import json
from multiprocessing import Pool
import re
from urllib.parse import parse_qs

username_regex = r"Posted by <@+.*>"

temp_list = []

app = Flask(__name__)

slack_access_token = os.environ.get("slack_access_token")
client_id = os.environ.get("client_id")

def download_file(url, file_id, channel_id, comment, user_id, timestamp):
	try:
		r = requests.get(url, headers={'Authorization': 'Bearer {}'.format(slack_access_token)})
		data = r.content
		imgur_upload_url = "https://api.imgur.com/3/image"
		headers = {'Authorization': 'Client-ID {}'.format(client_id), "content-type": "multipart/form-data"}
		r = requests.post(imgur_upload_url, headers=headers, data=data)
		try:
			link = r.json()['data']['link']
		except KeyError:
			link = "Failed"
		print(link)
		print("---Deleting File---")
		slack_file_delete = "https://slack.com/api/files.delete?token={}&file={}"
		resp = requests.post(slack_file_delete.format(slack_access_token, file_id))
		if not resp.json()['ok']:
			print("Not able to delete file")

		# print("here")
		# print(timestamp)
		resp = requests.post("https://slack.com/api/chat.delete?token={}&channel={}&ts={}".format(slack_access_token, channel_id, timestamp))
		if not resp.json()['ok']:
			print("Not able to delete file")

		# print("here")
		try:
			hook_headers = {"Authorization": "Bearer {}".format(slack_access_token), "Content-Type": "application/json; charset=utf-8"}
			message_data = json.dumps({"channel": channel_id, "text": "Posted by <@{}>\n{}\n{}".format(user_id, comment, link)})
			post_url = "https://slack.com/api/chat.postMessage"
			link_post = requests.post(post_url, headers=hook_headers, data=message_data)
			print(link_post.json())
		except Exception as err:
			print("Error : "+err)
	except Exception as error:
		print("Error:- ", error)


def delete_link(user_id, channel_id, ts):
	get_headers = {"Authorization": "Bearer {}".format(slack_access_token), "Content-Type": "application/x-www-form-urlencoded"}
	get_url = "https://slack.com/api/channels.history?channel={}&latest={}&inclusive=true&count=1".format(channel_id, ts)
	f = requests.get(get_url, headers=get_headers)
	text = f.json()['messages'][0]['text']
	match = re.finditer(username_regex, text)
	match = next(match)
	posted_user_id = match.group()[12:-1]
	print(posted_user_id, user_id)
	if posted_user_id == user_id:
		hook_headers = {"Authorization": "Bearer {}".format(slack_access_token), "Content-Type": "application/json; charset=utf-8"}
		message_data = json.dumps({"channel": channel_id, "ts": ts})
		post_url = "https://slack.com/api/chat.delete"
		link_delete = requests.post(post_url, headers=hook_headers, data=message_data)

def send_ephemeral(user_id, channel_id, file_permalink, file_id, comment, timestamp):
	print('-----Sending Ephemeral-----')
	slack_ephemeral_method = "https://slack.com/api/chat.postEphemeral"
	slack_ephemeral_json = {
	"attachments": [
		{
			"callback_id": "ephemeral_action",
			"attachment_type": "default",
			"text": "Would you like to upload this image to imgur?",
			"actions": [
				{
					"name": "response|{}|{}|{}|{}|{}|{}".format(user_id,channel_id,file_id,file_permalink,comment, timestamp),
					"text": "Yes, save space.",
					"type": "button",
					"value": "yes"
				},
				{
					"name": "noresponse",
					"text": "No, this image is private.",
					"type": "button",
					"value": "no",
					"style": "danger"
				}
			]
		}
	]
	}
	slack_ephemeral_json['user'] = user_id
	slack_ephemeral_json['channel'] = channel_id
	slack_ephemeral_json = json.dumps(slack_ephemeral_json)
	print(slack_ephemeral_json)  #print the json data to console
	url = slack_ephemeral_method.format(slack_access_token,)
	headers={'Authorization': 'Bearer {}'.format(slack_access_token),
			'Content-type': 'application/json'}
	r = requests.post(slack_ephemeral_method, headers=headers, data=slack_ephemeral_json)
	print(r)

pool = Pool(processes=10)


@app.route('/handle', methods=['GET','POST'])
def handle():
	try:
		url_data = request.get_data()
		print(url_data)
		'''Slacks interactive message request payload is in the form of
		application/x-www-form-urlencoded JSON string. Getting first actions parameter
		from it.'''
		url_data = json.loads(parse_qs(url_data.decode('utf-8'))['payload'][0])['actions'][0]
		eph_value = True if url_data['value'] == "yes" else False
		print(url_data['name'] + " : " + url_data['value'] + " : " + str(eph_value))
		if eph_value:
			params = url_data['name'].split('|')
			user_id = params[1]
			channel_id = params[2]
			file_id = params[3]
			file_permalink = params[4]
			comment = params[5]
			timestamp = params[6]
			i = pool.apply_async(download_file, [file_permalink, file_id, channel_id, comment, user_id, timestamp])
		else:
			print('---No chosen---')
	except Exception as err:
		print(err)
	finally:
		return jsonify({"response_type": "ephemeral",   "replace_original": "true",    "delete_original": "true",    "text": ""})


@app.route('/app', methods=['GET','POST'])
def hello():
	json_data = request.json
	# print(json.dumps(json_data, indent=4, sort_keys=True))
	try:
		challenge = json_data['challenge']
		return challenge
	except KeyError:
		try:
			try:
				if json_data['event']['type'] == 'reaction_added' and json_data['event']['reaction'] == 'x':
					channel_id = json_data['event']['item']['channel']
					ts = json_data['event']['item']['ts']
					user_id = json_data['event']['user']
					i = pool.apply_async(delete_link, [user_id, channel_id, ts])
			except KeyError as e:
				print("Err: ",e)

			# print("here")
			if json_data['event'] in temp_list:
				raise Exception('Already received. So ignoring this')
			temp_list.append(json_data['event'])
			
			file_id = json_data['event']['file']['id']
			file_info = requests.get("https://slack.com/api/files.info?token={}&file={}".format(slack_access_token, file_id))
			file_data = file_info.json()
			# print(json.dumps(file_data, indent=4, sort_keys=True))
			user_id = file_data['file']['user']
			channel_id = file_data['file']['channels'][0]
			timestamp = file_data['file']['shares']['public'][channel_id][0]['ts']
			# print(channel_id, timestamp, user_id)
			conversation = requests.get("https://slack.com/api/conversations.replies?token={}&channel={}&ts={}".format(
											slack_access_token,
											channel_id,
											timestamp
										))
			conversation_data = conversation.json()
			# print(conversation_data)
			# print(json.dumps(conversation_data, indent=4, sort_keys=True))
			try:
				comment = conversation_data['messages'][0]['text']
			except KeyError:
				comment = ''
			# print(comment)
			# print(json_data)
			if file_data['file']['size']/(1024**2) > 20:
				raise Exception("File too large (> 20MB)")
			file_permalink = file_data['file']['url_private_download']
			i = pool.apply_async(send_ephemeral, [user_id, channel_id, file_permalink, file_id, comment, timestamp])

		except Exception as err:
			print("Error:- " + err)
		finally:
			return ("ok", 200, {'Access-Control-Allow-Origin': '*'})
	except Exception as err:
		print("Error:- " + str(err))


if __name__ == '__main__':
	port = int(os.environ.get("PORT", 5000))  # the app is deployed on heroku
	app.run(host='0.0.0.0', port=port, debug=True)
