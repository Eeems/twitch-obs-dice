import ast
import asyncio
import os
import tomllib

import obsws_python as obs

from random import randint

from ruamel.yaml import YAML

from twitchAPI.chat import Chat
from twitchAPI.chat import ChatCommand
from twitchAPI.chat import EventData
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope
from twitchAPI.type import ChatEvent


async def roll_dice(
    name, spec: str, scene: str, displayTime: int
) -> tuple[list[str], int, list[list[int]]]:
    results = []
    result = 0
    dice = [x.split("d") for x in spec.split("+")]
    for die in dice:
        for i in range(0, int(die[0])):
            if die[1] in ("4", "6", "8", "12", "20"):
                value = randint(1, int(die[1]))
                results.append(str(value))
                result += value

            elif die[1] == "10":
                value = randint(0, 9)
                results.append(str(value))
                result += value

            elif die[1] == "100":
                value = randint(0, 9)
                results.append(str(value))
                result += value * 10

    scene_item_id = set_dice(
        f"Dice_!{name}",
        command["Dice"],
        results,
    )
    cl.set_scene_item_enabled(scene, scene_item_id, True)
    await asyncio.sleep(displayTime)
    cl.set_scene_item_enabled(scene, scene_item_id, False)

    return dice, result, results


def roll_command(name, command):
    if "Script" in command and command["Script"]:
        code = compile(
            command["Script"],
            "<script>",
            "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )

    condition = asyncio.Condition()

    async def func(cmd: ChatCommand):
        await condition.acquire()
        try:
            if "Dice" in command and command["Dice"]:
                dice, result, results = await roll_dice(
                    name,
                    command["Dice"],
                    config["OBS"]["Scene"],
                    command.get("DisplayTime", 5),
                )

            else:
                results = []
                result = 0
                dice = []

            if "Message" in command and command["Message"]:
                await cmd.reply(
                    command["Message"]
                    .replace("{user}", f"{cmd.user.name}")
                    .replace("{result}", str(result))
                )

            if "Script" in command and command["Script"]:
                try:
                    coroutine: Awaitable | None = eval(
                        code,
                        {
                            "chat": cmd.chat,
                            "config": config,
                            "obs": cl,
                            "roll_dice": roll_dice,
                            "twitch": cmd.chat.twitch,
                        },
                        {
                            "message": cmd,
                            "command": command,
                            "dice": dice,
                            "result": result,
                            "results": results,
                        },
                    )
                    if coroutine is not None:
                        await coroutine

                except Exception as e:
                    print(e)

        finally:
            condition.release()

    return func


def get_dimensions():
    video_settings = cl.get_video_settings()
    return video_settings.output_width, video_settings.output_height


def set_dice(name, dice, values):
    itemId = ensure_dice_source(name)
    color = config["Display"]["Color"]
    label = config["Display"]["Label"]
    chromaKey = config["Display"]["ChromaKey"]
    width, height = get_dimensions()
    cl.set_input_settings(
        name,
        {
            "url": (
                "https://dice.bee.ac/"
                f"?dicehex={color}"
                f"&labelhex={label}"
                f"&chromahex={chromaKey}"
                f"&d=1d{dice}@{'%20'.join(values)}"
                "&transparency=1"
                "&noresult"
                "&roll"
            ),
            "width": width,
            "height": height,
            "css": "",
            "reroute_audio": False,
            "shutdown": True,
        },
        True,
    )
    return itemId


def ensure_dice_source(name):
    scene = config["OBS"]["Scene"]
    width, height = get_dimensions()
    settings = {
        "url": "",
        "width": width,
        "height": height,
        "css": "",
        "reroute_audio": False,
        "shutdown": True,
    }
    if not [x for x in cl.get_input_list().inputs if x["inputName"] == name]:
        cl.create_input(scene, name, "browser_source", settings, False)

    cl.set_input_settings(name, settings, True)
    itemIds = [
        x["sceneItemId"]
        for x in cl.get_scene_item_list(scene).scene_items
        if x["sourceName"] == name
    ]
    if itemIds:
        itemId = itemIds[0]

    else:
        itemId = cl.create_scene_item(scene, name, False).scene_item_id

    cl.set_scene_item_transform(
        scene,
        itemId,
        {
            "boundsAlignment": 0,
            "width": width,
            "sourceWidth": width,
            "boundsWidth": width,
            "height": height,
            "sourceHeight": height,
            "boundsHeight": height,
            "boundsType": "OBS_BOUNDS_SCALE_INNER",
            "cropLeft": 0,
            "cropRight": 0,
            "cropTop": 0,
            "cropBottom": 0,
            "croptToBounds": False,
            "positionX": 0,
            "positionY": 0,
            "scaleX": 1.0,
            "scaleY": 1.0,
        },
    )
    cl.set_scene_item_locked(scene, itemId, True)
    for f in cl.get_source_filter_list(name).filters:
        cl.remove_source_filter(name, f["filterName"])

    cl.create_source_filter(
        name,
        "Chroma Key",
        "chroma_key_filter_v2",
        {"key_color_type": "custom", "color": config["Display"]["ChromaKey"]},
    )
    return itemId


async def on_ready(ready_event: EventData):
    await ready_event.chat.join_room(config["Twitch"]["Channel"])


async def run():
    twitch = await Twitch(
        config["Twitch"]["ClientId"], config["Twitch"]["ClientSecret"]
    )
    scope = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]
    auth = UserAuthenticator(twitch, scope)
    token, refresh_token = await auth.authenticate()
    await twitch.set_user_authentication(token, scope, refresh_token)
    chat = await Chat(twitch)
    chat.register_event(ChatEvent.READY, on_ready)
    for name, command in config["Commands"].items():
        chat.register_command(name, roll_command(name, command))

    chat.start()

    try:
        input("press ENTER to stop\n")

    finally:
        chat.stop()
        await twitch.close()


yaml = YAML()
if os.path.exists("config.toml"):
    print("Upgrading configuraton...")
    with open("config.toml", "rb") as f:
        config = tomllib.load(f)

    config["Commands"] = {x["Name"]: x for x in config["General"]["Commands"]}
    for x in config["Commands"].values():
        del x["Name"]

    del config["General"]["Commands"]
    config["Display"] = config["General"]
    del config["General"]

    with open("config.yml", "w") as f:
        yaml.dump(config, f)

    os.unlink("config.toml")

print("Reading configuraton...")
with open("config.yml", "r") as f:
    config = yaml.load(f)


print("Connecting...")
cl = obs.ReqClient(
    host=config["OBS"]["Host"],
    port=config["OBS"]["Port"],
    password=config["OBS"]["Password"],
    timeout=3,
)

asyncio.run(run())
