from dotenv import load_dotenv
load_dotenv()
import discord
import botometer
import re
import os
from web3.auto.infura import w3


mashape_key = os.getenv("MASHAPE_KEY")
twitter_app_auth = {
    'consumer_key': os.getenv("TWITTER_CONSUMER_KEY"),
    'consumer_secret': os.getenv("TWITTER_CONSUMER_SECRET"),
    'access_token': os.getenv("TWITTER_ACCESS_TOKEN"),
    'access_token_secret': os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
  }
bom = botometer.Botometer(wait_on_ratelimit=True,
                          mashape_key=mashape_key,
                          **twitter_app_auth)

twitter_humanity_applicant_abi = [{"constant":False,"inputs":[{"name":"who","type":"address"},{"name":"username","type":"string"}],"name":"applyWithTwitterFor","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"nonpayable","type":"function"},{"constant":False,"inputs":[{"name":"who","type":"address"}],"name":"applyFor","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"nonpayable","type":"function"},{"constant":False,"inputs":[{"name":"who","type":"address"},{"name":"username","type":"string"}],"name":"applyWithTwitterUsingEtherFor","outputs":[{"name":"","type":"uint256"}],"payable":True,"stateMutability":"payable","type":"function"},{"constant":True,"inputs":[],"name":"humanity","outputs":[{"name":"","type":"address"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":False,"inputs":[{"name":"who","type":"address"}],"name":"applyWithEtherFor","outputs":[{"name":"","type":"uint256"}],"payable":True,"stateMutability":"payable","type":"function"},{"constant":True,"inputs":[],"name":"governance","outputs":[{"name":"","type":"address"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":True,"inputs":[],"name":"registry","outputs":[{"name":"","type":"address"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":False,"inputs":[{"name":"username","type":"string"}],"name":"applyWithTwitterUsingEther","outputs":[{"name":"","type":"uint256"}],"payable":True,"stateMutability":"payable","type":"function"},{"constant":True,"inputs":[],"name":"exchange","outputs":[{"name":"","type":"address"}],"payable":False,"stateMutability":"view","type":"function"},{"constant":False,"inputs":[{"name":"username","type":"string"}],"name":"applyWithTwitter","outputs":[{"name":"","type":"uint256"}],"payable":False,"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"_governance","type":"address"},{"name":"_registry","type":"address"},{"name":"_humanity","type":"address"},{"name":"_exchange","type":"address"}],"payable":False,"stateMutability":"nonpayable","type":"constructor"},{"payable":True,"stateMutability":"payable","type":"fallback"},{"anonymous":False,"inputs":[{"indexed":True,"name":"proposalId","type":"uint256"},{"indexed":True,"name":"applicant","type":"address"},{"indexed":False,"name":"username","type":"string"}],"name":"Apply","type":"event"}]
twitter_humanity_applicant = w3.eth.contract(
    address='0x9D661f7773Be14439b4223F5b516bC7Ef67b0369',
    abi=twitter_humanity_applicant_abi
)


class MyClient(discord.Client):
    async def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    async def on_message(self, message):
        # we do not want the bot to reply to itself
        if message.author.id == self.user.id:
            return

        if not (message.content.startswith('!Verify') or message.content.startswith('!verify')):
            return
        else:
            await message.channel.trigger_typing()

        # Extract twitter name
        m = re.search('(@\w+)', message.content)
        if m is None:
            await message.channel.send(
                "Could not find the twitter username, please use '!Verify @theusername' as the command"
            )
            return

        twitter_name = m.group()

        # Search for HumanityDAO tweet
        recent_tweets = bom.twitter_api.user_timeline(twitter_name)

        # Get the Ethereum address from the tweet
        eth_addr = None
        for t in recent_tweets:
            if any(user_mention['id'] == 1118447927112781824 for user_mention in t['entities']['user_mentions']):
                # Tweet about HumanityDAO found, now time to extract the Ethereum address
                eth_addr_regex = re.search('(0x[0-9a-f]{40})', t['text'])
                if eth_addr_regex is not None:
                    if eth_addr is None:
                        eth_addr = eth_addr_regex.group()
                        await message.channel.send(
                            "[OK] Found tweet with Ethereum address %s for %s" % (eth_addr, twitter_name)
                        )
                    elif eth_addr != eth_addr_regex.group():
                        # Multiple tweets with diverting eth addresses, this is a problem!
                        await message.channel.send(
                            "[WARNING] Account %s posted multiple tweets with different "
                            "ethereum addresses, aborting" % twitter_name
                        )
                        return
        if eth_addr is None:
            await message.channel.send(
                "[WARNING] Couldn't detect tweet with Ethereum address for %s" % twitter_name
            )
            return

        await message.channel.trigger_typing()
        # Compare Ethereum address with the one registered in HumanityDAO smart contract
        event_filter = twitter_humanity_applicant.events.Apply.createFilter(
            fromBlock=0,
            toBlock="latest",
            argument_filters={'applicant': eth_addr}
        )
        applicant_events = event_filter.get_all_entries()
        if not applicant_events:
            await message.channel.send(
                "[WARNING] Couldn't find any on-chain applications for HumanityDAO with Ethereum address %s" % eth_addr
            )
            return
        else:
            await message.channel.send(
                "[OK] Verified Ethereum address %s in application for %s" % (eth_addr, twitter_name)
            )

        await message.channel.trigger_typing()
        # Check bot score
        result = bom.check_account(twitter_name)

        if any(score > 0.3 for score in result["scores"].values()):
            await message.channel.send(
                "[WARNING] The twitter account might be a bot, check manually. "
                "The following scores (0 = human, 5=bot) have been determined: %s"
                % (" ".join("%s: %1.1f" % (k, v) for k, v in result["display_scores"].items()))
            )
        elif any(score > 0.8 for score in result["scores"].values()):
            await message.channel.send(
                "[WARNING] The twitter account is very likely a bot!!! "
                "The following scores (0 = human, 5=bot) have been determined: %s"
                % (" ".join("%s: %1.1f" % (k, v) for k, v in result["display_scores"].items()))
            )
        else:
            await message.channel.send(
                "[OK] This twitter account doesn't look like a bot"
            )

        await message.channel.send(
            "All done, nothing more to check"
        )



from http.server import BaseHTTPRequestHandler
from cowpy import cow


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type','text/plain')
        self.end_headers()
        message = cow.Cowacter().milk('HumanityDAO Discord Bot')
        self.wfile.write(message.encode())
        return


client = MyClient()
client.run(os.getenv("DISCORD_BOT_TOKEN"))
