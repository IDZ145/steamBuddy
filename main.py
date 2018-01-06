"""
    This is a simple discord bot that will tell what games people share in common.

    This needs to use postgres as this uses postgres arrays when trying to find the games the users own
"""
import asyncio
import json
import ast
import discord
import aiohttp
import async_timeout
import steam
import psycopg2
from scanf import scanf

#The keys required
DISCORD_API_KEY = #Put your discord API key here
STEAM_WEB_API_KEY = #Put you steam API key here
#These are the database parameters
params = {
  'database': #dbname
  'user': #dbusername
  'password': #dbpassword
  'host': #dbhost
  'port': #dbport
}


client = discord.Client()
#initialising the all the connections needed
api = steam.webapi.WebAPI(key=STEAM_WEB_API_KEY)
conn = psycopg2.connect(**params)
curr = conn.cursor()

def insert_game(cursor, game, steamid):
    """This will add a game to a steam user in the database
    Arguments:
        cursor {database cursor} -- This is a cursor connection to the database
        game {int} -- The id of the game
        steamid {int} -- The steamid of the user
    """

    cursor.execute("INSERT INTO gamesowned (steamid, gameid) VALUES (%s, %s) on conflict do nothing", (steamid, game["appid"]))

def add_games(steam_api, cursor, steamid):
    """Add games from a steam user
    Arguments:
        steam_api {steam} -- The api class used to connect to steam
        cursor {database cursor} -- The cursor of the database you want to connect to
        steamid {int} -- The steam id of the user
    Returns:
        [int] -- The number of games added
    """

    raw_json = steam_api.IPlayerService.GetOwnedGames(steamid=steamid, include_appinfo=False, include_played_free_games=False, appids_filter=0)
    game_library = ast.literal_eval(str(raw_json))
    game_count = game_library['response']['game_count']
    if isinstance(game_library['response']['games'], list) :
        for game in game_library['response']['games']:
            insert_game(cursor, game, steamid)
    else:
        insert_game(cursor, game_library['response']['games'], steamid)
    return game_count

def add_user(cursor, steam_api, url, author):
    """Add a steam user to a discord user in the app
    Arguments:
        cursor {database cursor} -- The database cursor
        steam_api {steam} -- The steam api class that wraps the user
        url {string} -- The url of the steam user
        author {int} -- The author of the message which will be the discord user
    """
    steam_user_id = steam.steamid.steam64_from_url(url)
    if steam_user_id is None:
        return -1
    try:
        cursor.execute("INSERT INTO owner (steamid, discordid) VALUES (%s, %s) on conflict do nothing", (steam_user_id, int(author)))
        return add_games(steam_api, cursor, steam_user_id)
    except:
        return -1

def update_games(cursor,discordid):
    """Update all the steam accounts linked to the user
    
    Arguments:
        cursor {database cursor} -- The cursor of the database
        discordid {int} -- The id of the discord user
    """

    cursor.execute("select owner.steamid from owner where owner.discordid = %s", (discordid, ))
    rows = cursor.fetchall()
    added_games = 0
    for steam_id in rows:
        added_games = added_games + add_games(api,cursor,steam_id[0])
    return added_games

async def fetch(session, url):
    """
    This is used to help wrap the asyncio aiohttp library so it will be easy to call the api
    """

    with async_timeout.timeout(10):
        async with session.get(url) as response:
            return await response.text()

async def print_games(cursor, users, channel, threshold):
    """
        This will find all the games that the user share in common.
        The threshold is used to limit the number of entries printed
    """

    cursor.execute("select gamesowned.gameid, owner.discordid from gamesowned , owner where owner.discordid = ANY (%s) and owner.steamid = gamesowned.steamid GROUP BY gamesowned.gameid , owner.discordid ORDER BY gamesowned.gameid , owner.discordid", (users, ))
    rows = cursor.fetchall()
    games = dict()
    for row in rows:
        if row[0] in games:
            games[row[0]].append(row[1])
        else:
            games[row[0]] = [row[1]]
    key_list = sorted(games, key=lambda k: len(games[k]), reverse=True)
    i = 0
    j = 0
    while i < len(key_list) and  j < threshold:
        async with aiohttp.ClientSession() as session:
            raw_json = await fetch(session, "http://store.steampowered.com/api/appdetails?appids={0}".format(int(key_list[i])))
            game = json.loads(str(raw_json))
            if game[str(key_list[i])]["success"]:
                j = j + 1
                if game[str(key_list[i])]["data"]["type"] == "game":
                    data = game[str(key_list[i])]["data"]
                    flag = True
                    genres = str()
                    for g in data["genres"]:
                        if flag:
                            genres = g["description"]
                            flag = False
                        else:
                            genres = genres + "," + g["description"]
                    user_list = str()
                    for user in games[key_list[i]]:
                        u = await client.get_user_info(user)
                        user_list = user_list + " " + u.mention
                    store_link = "http://store.steampowered.com/app/{0}/".format(key_list[i])
                    tmp = await client.send_message(channel,
'''
**name**: {0}
**genres**: {1}
**users**: {2}
**store link**: {3}
'''.format(data["name"], genres, user_list, store_link))
        i = i + 1

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')

@client.event
async def on_message(message):
    if message.content.startswith('!ping'):
        tmp = await client.send_message(message.channel, 'Still alive')
    elif message.content.startswith('!help'):
        tmp = await client.send_message(message.channel, 
"""
A bot for finding steam games you share in common with your friends
You can also add more than one steam account to you discord account
Disclaimers:
This bot will store your
    - steam ids of added users
    - discord id of all added users 
    - the ids of all the games in the steam libraries of the added users

Commands:
    !ping: see if the bot is still running
    !help: get help for commands
    !steamBuddy add: This will add a user
        !steamBuddy add { url }
            - url: The users steam profile url
    !steamBuddy find: This will find the top 10 (By default) games that the mentioned list of users share and is sorted by how many people share the game
        !steamBuddy find { limit } [ mention ]
            - limit { optional } : How many games you want displayed
            - mention: The users you want to see who share games @example
    !steamBuddy update: This will update the list of games you own
        !steamBuddy update
"""
        )
    elif message.content.startswith('!steamBuddy add'):
        url = message.content[15:].rstrip().lstrip()
        if url.startswith('http://steamcommunity.com/id/'):
            result = add_user(curr, api, url, message.author.id)
            if  result < 0:
                tmp = await client.send_message(message.channel, 'Could not add you')
            else:
                if result != 1:
                    tmp = await client.send_message(message.channel, 'I found {0} non free games in your library'.format(result))
                else:
                    tmp = await client.send_message(message.channel, 'I found 1 non free games in your library')
            conn.commit()
        else:
            tmp = await client.send_message(message.channel, 'In valid url should be http://steamcommunity.com/id/{stuff}')
    elif message.content.startswith('!steamBuddy find'):
        args = scanf("!steamBuddy find %d", message.content)
        if args is None:
            limit = 10
        else:
            limit = args[0]
        chn = message.channel
        user_list = list()
        for user in message.mentions:
            user_list.append(int(user.id))
        await print_games(curr, user_list, chn, limit)
    elif message.content.startswith('!steamBuddy update'):
        added_games = update_games(curr,message.author.id)
        tmp = await client.send_message(message.channel, 'I found {0} non free games in your libraries'.format(added_games))

#This needs to be at the end
client.run(DISCORD_API_KEY)
