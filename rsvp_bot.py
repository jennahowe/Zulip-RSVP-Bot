import zulip
import requests
import re
import pprint
import os
#from database import VotingTopics


class Bot():

    ''' bot takes a zulip username and api key, a word or phrase to respond to,
        a search string for giphy, an optional caption or list of captions, and
        a list of the zulip streams it should be active in. It then posts a
        caption and a randomly selected gif in response to zulip messages.
    '''

    def __init__(self, zulip_username, zulip_api_key, key_word,
                 subscribed_streams=[]):
        self.username = zulip_username
        self.api_key = zulip_api_key
        self.key_word = key_word.lower()
        self.subscribed_streams = subscribed_streams
        self.client = zulip.Client(zulip_username, zulip_api_key)
        self.subscriptions = self.subscribe_to_streams()
        self.voting_topics = {}

    @property
    def streams(self):
        ''' Standardizes a list of streams in the form [{'name': stream}]
        '''
        if not self.subscribed_streams:
            streams = [{'name': stream['name']}
                       for stream in self.get_all_zulip_streams()]
            return streams
        else:
            streams = [{'name': stream} for stream in self.subscribed_streams]
            return streams

    def get_all_zulip_streams(self):
        ''' Call Zulip API to get a list of all streams
        '''
        response = requests.get('https://api.zulip.com/v1/streams',
                                auth=(self.username, self.api_key))

        if response.status_code == 200:
            return response.json()['streams']

        elif response.status_code == 401:
            raise RuntimeError('check yo auth')

        else:
            raise RuntimeError(':( we failed to GET streams.\n(%s)' % response)

    def subscribe_to_streams(self):
        ''' Subscribes to zulip streams
        '''
        self.client.add_subscriptions(self.streams)

    def respond(self, msg):
        ''' checks msg against key_word. If key_word is in msg, gets a gif url,
            picks a caption, and calls send_message()
        '''
        content = msg['content'].split()[0].lower().strip()

        if self.key_word == content and msg["sender_email"] != self.username:
            self.parse_public_message(msg)

        elif msg["type"] == "private" and msg["sender_email"] != self.username:
            self.parse_private_message(msg)

    def send_message(self, msg):
        ''' Sends a message to zulip stream
        '''
        if msg["type"] == "stream":
            msg["to"] = msg['display_recipient']

        elif msg["type"] == "private":
            msg["to"] = msg["sender_email"]

        self.client.send_message(msg)

    def parse_public_message(self, msg):
        '''Parse public message given to the bot.

        The resulting actions can be:
            -send_results
            -add_vote
            -send_help
            -post_error
            -new_voting_topic
            -add_voting_option
        '''

        title = self._parse_title(msg)

        if title.lower() == "help":
            self.send_help(msg)

        elif title.lower() in self.voting_topics.keys():
            split_msg = msg["content"].split("\n")

            if len(split_msg) == 2:
                keyword = split_msg[1]
                regex = re.compile("[0-9]+")

                if keyword.lower().strip() == "who's in":
                    self.send_results(msg)

                elif keyword.lower().strip() == "i'm in":
                    print 'rsvp recorded'
                    self.add_vote(title.lower(), 0, msg)

                elif regex.match(keyword):
                    self.add_vote(title.lower(), int(keyword), msg)

                else:
                    self.send_help(msg)
            else:
                self.post_error(msg)
        else:
            self.new_voting_topic(msg)

    def _parse_title(self, msg):
        title = msg["content"].split("\n")[0].split()[1:]
        return " ".join(title)

    def parse_private_message(self, msg):
        '''Parse private message given to the bot.

        The resulting actions can be:
            -add_vote
            -send_voting_help
            -post_error
        '''

        msg_content = msg["content"].lower()
        title = msg_content.split("\n")[0]

        if title.strip() in self.voting_topics.keys():
            split_msg = msg_content.split("\n")

            if len(split_msg) == 2:
                regex = re.compile("[0-9]+")
                option_number = split_msg[1].split(" ")[0]

                if regex.match(option_number):
                    option_number = int(option_number)
                    self.add_vote(title.lower(), option_number, msg)

                else:
                    print "regex did not match"
                    self.send_voting_help(msg)
            else:
                self.post_error(msg)
        else:
            print "title not in keys" + title
            pprint.pprint(self.voting_topics)
            self.send_voting_help(msg)

    def new_voting_topic(self, msg):
        '''Create a new voting topic.'''

        msg_content = msg["content"]
        title = msg_content.split("\n")[0].split()[1:]
        title = " ".join(title).strip()

        if title:
            msg["content"] = title
            options = msg_content.split("\n")[1:]
            options_dict = {0: ['Default', 0, [], []]}

            for x in range(len(options)):
                options_dict[x] = [options[x], 0, [], []]
                msg["content"] += "\n " + str(x) + ". " + options[x]

            self.voting_topics[title.lower().strip()] = {"title": title,
                                                         "options": options_dict,
                                                         "people_who_have_voted": {}}
            self.send_message(msg)

        else:
            self.send_help(msg)

    def add_voting_option(self, msg, title, new_voting_option):
        '''Add a new voting option to an existing voting topic.'''

        if title.lower().strip() in self.voting_topics:
            vote = self.voting_topics[title.lower().strip()]
            options = vote["options"]

            if self._not_already_there(options, new_voting_option):
                options_num = options.keys()
                new_option_num = len(options_num)

                options[new_option_num] = [new_voting_option, 0]

                msg["content"] = "There is a new option in topic: " + title
                for x in range(len(options)):
                    msg["content"] += "\n " + str(x) + ". " + options[x][0]

                self.send_message(msg)

            else:
                msg["content"] = new_voting_option + \
                    " is already an option in topic: " + title + \
                    "\nDo not attempt to repeat options!"
                self.send_message(msg)

        self.voting_topics[title.lower().strip()] = vote

    def _not_already_there(self, vote_options, new_voting_topic):
        return True

    def add_vote(self, title, option_number, msg):
        '''Add a vote to an existing voting topic.'''

        vote = self.voting_topics[title.strip()]

        if option_number in vote["options"]:

            if msg["sender_email"] not in vote["people_who_have_voted"]:
                vote["options"][option_number][1] += 1
                vote["options"][option_number][2].append(msg["sender_email"])
                vote["options"][option_number][3].append(msg["sender_full_name"])
                print vote

                vote["people_who_have_voted"][
                    (msg["sender_email"])] = option_number
                msg["content"] = self._get_add_vote_msg(msg, vote,
                                                        option_number, False)

            else:
                vote_option_to_decrement = vote[
                    "people_who_have_voted"][msg["sender_email"]]
                vote["options"][vote_option_to_decrement][1] -= 1
                vote["options"][option_number][1] += 1
                vote["people_who_have_voted"][
                    (msg["sender_email"])] = option_number
                msg["content"] = self._get_add_vote_msg(msg, vote,
                                                        option_number, True)
        else:
            msg["content"] = "That option is not in the range of the voting options. Here are your options: \n" + \
                             "\n".join([str(num) + ". " + option[0]
                                        for num, option in vote["options"].items()])

        self.send_message(msg)

        self.voting_topics[title.strip()] = vote

    def _get_add_vote_msg(self, msg, vote, option_number, changed_vote):
        '''Creates a different msg if the vote was private or public.'''

        option_desc = vote["options"][option_number][0]

        if changed_vote:
            msg_content = "You have changed your vote. \n"
        else:
            msg_content = ""
        if msg["type"] == "private":
            msg_content += "One vote in this topic: " + vote["title"] + \
                " for this option: " + option_desc
        else:
            msg_content += "You just voted for '" + option_desc + \
                "' but remember! You can also vote privately if you want :)"

        return msg_content

    def send_help(self, msg):
        with open("help_msg.txt") as f:
            msg["content"] = f.read()
        self.send_message(msg)

    def send_voting_help(self, msg):
        with open("voting_help_msg.txt") as f:
            msg["content"] = f.read()
        self.send_message(msg)

    def post_error(self, msg):
        return

    def send_results(self, msg):
        '''Publicly send results of voting in the thread that was used.'''

        msg_content = msg["content"].lower()
        title = msg_content.split("\n")[0].split()[1:]
        title = " ".join(title).strip()

        if title in self.voting_topics.keys():
            vote = self.voting_topics[title]
            results = vote["title"]

            if len(vote["options"]) == 1:
                import pdb; pdb.set_trace()
                results += " participants (" + str(vote["options"][0][1]) + "): "
                results += ', '.join(vote["options"][0][3])

                #results += "\nParticipants' emails: "
            else:

                for option in vote["options"].values():

                    results += "\n{0} participants ({1}): ".format(
                        option[0], str(option[1]))
                    results += ', '.join(option[3])

            msg["content"] = results
            self.send_message(msg)
            del self.voting_topics[title]

        self.voting_topics[title.lower().strip()] = vote

    def main(self):
        ''' Blocking call that runs forever. Calls self.respond() on every
            message received.
        '''
        self.client.call_on_each_message(lambda msg: self.respond(msg))
        # print msg


def main():
    zulip_username = 'rsvpbot-bot@students.hackerschool.com'
    zulip_api_key = os.environ['ZULIP_API_KEY']
    key_word = 'RSVPbot'

    subscribed_streams = []

    new_bot = Bot(zulip_username, zulip_api_key, key_word, subscribed_streams)
    new_bot.main()

if __name__ == '__main__':
    main()
