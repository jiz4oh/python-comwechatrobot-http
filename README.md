```
from wechatrobot import WeChatRobot


bot = WeChatRobot()

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

`SendText`、`SendQuoteText`、`SendAt`、`SendCard`、`SendImage`、`SendFile`、`SendArticle`、`SendApp`、`SendXml`、`SendEmotion` 和 `ForwardMessage` 成功时，响应包含字符串形式的服务器消息 ID：

```python
response = bot.SendText(wxid="filehelper", msg="hello")
# {"msg": 1, "result": "OK", "svrid": "1234567890123456789"}
```

`RevokeMessage` 只返回撤回结果，不返回 `svrid`。Native 已接受发送但未取得服务器消息 ID 时返回 `result: ERROR`，调用方无需再按内容、时间或文件路径匹配自发消息。
