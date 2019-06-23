from dotenv import load_dotenv
load_dotenv()
import discord
import botometer
import re
import os
import asyncio
from web3.auto.infura import w3
import logging
logging.basicConfig(level=logging.INFO)
from tweepy.error import TweepError

logging.info("Starting HumanityDAO bot")


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


class HumanityDAODiscordBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # create the background task and run it in the background
        logging.info("Going to start background polling")
        self.bg_wait_for_new_applicants = self.loop.create_task(self.wait_for_new_applicants())

    def find_ethereum_address_in_tweet(self, twitter_handle):
        """ Find for the given twitter user the tweeted Ethereum address mentioned in the application for HumanityDAO

        :param twitter_handle: (String) twitter username
        :returns: (String) Ethereum address which this user tweeted to
        :raises: LookupError if there was an issue with finding a (unique) address
        """
        # Search for HumanityDAO tweet
        try:
            recent_tweets = bom.twitter_api.user_timeline(twitter_handle)
        except TweepError as e:
            # Potentially invalid twitter user
            raise LookupError("Error when searching for tweet: %s" % e)

        # Get the Ethereum address from the tweet
        eth_addr = None
        for t in recent_tweets:
            if any(user_mention['id'] == 1118447927112781824 for user_mention in t['entities']['user_mentions']):
                # Tweet about HumanityDAO found, now time to extract the Ethereum address
                eth_addr_regex = re.search('(0x[0-9a-f]{40})', t['text'])
                if eth_addr_regex is not None:
                    if eth_addr is None:
                        eth_addr = eth_addr_regex.group()
                    elif eth_addr != eth_addr_regex.group():
                        # Multiple tweets with diverting eth addresses, this is a problem!
                        raise LookupError("Found multiple tweets with diverting ETH addresses!")

        if eth_addr is None:
            raise LookupError("Couldn't find any tweet regarding HumanityDAO with a valid Ethereum address")

        return eth_addr

    def verify_tweet(self, twitter_handle, ethereum_address):
        """ Verify if the given twitter user tweeted the given Ethereum address to verify as human

        :param twitter_handle: (String) twitter username
        :param ethereum_address: (String) Ethereum address
        :raises: LookupError if the twitter user didn't tweet the given address
        """
        # Get the Ethereum address from the tweet
        eth_addr = self.find_ethereum_address_in_tweet(twitter_handle)

        if eth_addr.lower() != ethereum_address.lower():
            raise LookupError("Tweet has different Ethereum address: %s != %s" %(eth_addr, ethereum_address))

    def get_twitter_users_for_applicant_address(self, application_address):
        """ Finds the twitter username when given an application address

        :param application_address: (String) Ethereum address
        :return: All twitter usernames who used this application address
        """
        event_filter = twitter_humanity_applicant.events.Apply.createFilter(
            fromBlock=0,
            toBlock="latest",
            argument_filters={'applicant': application_address}
        )
        applicant_events = event_filter.get_all_entries()

        return [e.args.username for e in applicant_events]

    async def on_ready(self):
        logging.info('Logged in as %s (%s)' % (self.user.name, self.user.id))

    async def wait_for_new_applicants(self):
        """ Poll Ethereum for new applications and check if they are valid

        :return: None
        """
        logging.info("Starting background polling - waiting until ready")
        await self.wait_until_ready()
        logging.info("Starting background polling - ready")

        channel = self.get_channel(int(os.getenv("NEW_APPLICANT_VERIFY_CHANNEL")))
        last_checked_block = int(os.getenv("FIRST_BLOCK"))

        while not self.is_closed():
            logging.info("Polling for new entries")
            # Prepare filter to use for searching for new applicants
            latest_block = w3.eth.getBlock('latest')["number"]
            # Preferring to re-create filter every time as it might have timed out anyways
            event_filter = twitter_humanity_applicant.events.Apply.createFilter(
                fromBlock=last_checked_block,
                toBlock=latest_block
            )
            applicant_events = event_filter.get_all_entries()
            logging.info("Found %i new applicants from block %i to %i" % (
                len(applicant_events),
                last_checked_block,
                latest_block
            ))
            last_checked_block = latest_block

            for event in applicant_events:
                # Get new user twitter handle
                twitter_handle = event.args.username
                ethereum_address = event.args.applicant
                proposal_id = event.args.proposalId

                logging.info("Handling applicant %s (Proposal %i, address %s)" % (
                    twitter_handle, proposal_id, ethereum_address
                ))

                await channel.send(
                    "New applicant found! Going to check proposal %i for user %s (%s) now..." % (
                        proposal_id, twitter_handle, ethereum_address
                    )
                )

                # Verify tweet
                try:
                    self.verify_tweet(twitter_handle, ethereum_address)
                except LookupError as e:
                    await channel.send(
                        "[WARNING] New applicant %s with proposal %i didn't tweet address %s!" % (
                            twitter_handle, proposal_id, ethereum_address
                        )
                    )
                    logging.warning(e)
                    continue

                # Check for twitter bot
                await channel.trigger_typing()
                result = bom.check_account(twitter_handle)

                if any(score > 0.3 for score in result["scores"].values()):
                    await channel.send(
                        "[WARNING] The twitter account might be a bot, check manually. "
                        "The following scores (0 = human, 5=bot) have been determined: %s"
                        % (" ".join("%s: %1.1f" % (k, v) for k, v in result["display_scores"].items()))
                    )
                    continue
                elif any(score > 0.8 for score in result["scores"].values()):
                    await channel.send(
                        "[WARNING] The twitter account is very likely a bot!!! "
                        "The following scores (0 = human, 5=bot) have been determined: %s"
                        % (" ".join("%s: %1.1f" % (k, v) for k, v in result["display_scores"].items()))
                    )
                    continue

                await channel.send(
                    "[OK] Looks good! Please welcome %s to HumanityDAO!" % twitter_handle
                )

            logging.info("Completed automatic check for new applicants")

            await asyncio.sleep(15)

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

        # Search for tweeted Ethereum address - only way as we can't search for twitter applicants in Ethereum directly
        try:
            await message.channel.trigger_typing()
            eth_addr = self.find_ethereum_address_in_tweet(twitter_name)
            await message.channel.send(
                "[OK] Found tweet with Ethereum address %s for %s" % (eth_addr, twitter_name)
            )
        except LookupError as e:
            await message.channel.send(
                "[WARNING] Applicant %s didn't tweet his application correctly! Error: %s" % (
                    twitter_name, e
                )
            )
            logging.warning(e)
            return

        # Search on Ethereum for the applicant address and compare with twitter user
        await message.channel.trigger_typing()
        twitter_names = self.get_twitter_users_for_applicant_address(eth_addr)

        # Make sure that we found something
        if not twitter_names:
            await message.channel.send(
                "[WARNING] Couldn't find any on-chain applications for HumanityDAO for %s" % eth_addr
            )
            return

        # Make sure that if there are multiple applications, they always use the same address
        if not all([twitter_names[0] == name for name in twitter_names]):
            await message.channel.send(
                "[WARNING] Applicant %s applied with multiple different twitter handles" % eth_addr
            )
            return

        await message.channel.send(
            "[OK] Verified address %s in tweet and on-chain to be identical" % eth_addr
        )

        # Check if user is a bot
        await message.channel.trigger_typing()
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


client = HumanityDAODiscordBot()
client.run(os.getenv("DISCORD_BOT_TOKEN"))
