Installation
============

- Go to https://dev.twitch.tv/console and create a new application.
- Set the OAuth Redirection URL to http://localhost:17563
- Set Category to Chat Bot
- Set the Client Type to Confidential
- Save
- Copy/rename config.example.yml to config.yml
- Set ClientId to the value for the application you created in https://dev.twitch.tv/console/apps
- Set ClientSecret to a new the value generated for the application you created in https://dev.twitch.tv/console/apps
- Set the Scene to the name of the scene you want the dice to be added to
- Set the OBS connection information to the connections settings found in OBS under Tools > WebSocket Server Settings > Show Connect Info
- Run the bot

Configuration
=============

Display
-------

Color: Colour of the dice.
Label: Colour of the numbers on the dice.
ChromaKey: Colour used for the background that is filtered out. This can affect the colour of the dice, so you may need to change this to get your dice to display the way you want them to.


Twitch
------

ClientId: Client Id found in https://dev.twitch.tv/console/apps
ClientSecret: Client secret found in https://dev.twitch.tv/console/apps
Channel: Channel name to listen to chat for

OBS
---

Scene: Scene in OBS to inject the dice roll browser sources. Add this scene as an item on your active scene to control where the dice are displayed.
Host: Host/IP for OBS websocket server
Port: Port for OBS websocket server
Password: Password for OBS websocket server

Commands
--------

You can add another named commands that the bot will register. The key for the command will be the twitch command that is registered to trigger this command. For example a key of `roll:` will mean that it executes when a user says `!roll`

Dice: Dice specification to roll. e.g. 2d20+1d10
Message: Message to reply to the user with in twitch chat. `{user}` will be replaced with the username and `{result}` will be replaced with the dice total that was rolled.
DisplayTime: How long to display the dice roll for in seconds. Defaults to 5 seconds.
Script: Python script to run for this command.


Python Scripts
--------------

Python script have the following global variables available:

- `chat`: TwitchAPI Chat instance
- `config`: Configuration dictionary generated from the contents in `config.yml`
- `obs`: OBS websocket instance
- `roll_dice`: Method to display a dice roll and display the results
- `twitch`: TwitchAPI instance

Python scripts have the following local variables available:

- `message`: TwitchAPI ChatCommand instance
- `command`: Specific command configuration for this command
- `dice`: Dice spec
- `result`: Total of all the dice rolled
- `results`: Breakdown of the different dice results. This can be cross referenced with `dice` to see which dice is of what type.
