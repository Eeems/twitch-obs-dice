Configuration
=============

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
