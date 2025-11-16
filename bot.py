from flask import Flask
import time

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

if __name__ == "__main__":
    print("Bot is running successfully!")
    while True:
        time.sleep(1)
