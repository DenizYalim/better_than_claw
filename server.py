import flask

app = flask.Flask(__name__)
PORT = 5000


def callWebhook():
    # Webhook that's called by telegram when a message is sent to the bot
    pass
