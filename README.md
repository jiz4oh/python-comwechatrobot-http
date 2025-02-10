```
from wechatrobot import WeChatRobot


url = "http://127.0.0.1:18888"  # comwechat http 接口地址
bot = WeChatRobot(url)

@bot.on("friend_msg")
def on_friend_msg(msg):
    bot.SendText(wxid = msg['sender'], msg = msg['message'])

@bot.on("group_msg")
def on_group_msg(msg):
    print(f"on_group_msg: {msg}")

@bot.on("self_msg")
def on_self_msg(msg):
    print(f"on_self_msg: {msg}")

bot.run()
```
