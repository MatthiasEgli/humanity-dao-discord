FROM kennethreitz/pipenv

COPY . /app

CMD python3 discord_bot.py
