
import argparse
import json
import math
import os
import random
import queue
import re
import time
import nodriver as uc
import requests
import subprocess
import threading
import multiprocessing
import numpy as np
from pdf2image import convert_from_path
import pytesseract
from PIL import Image

from bs4 import BeautifulSoup as BS
from shared import *
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

"""
	What is a Barrel
	https://www.mlb.com/glossary/statcast/barrel

	General: >= 98 EVO && 26 <= LA <= 30
	99 EVO (25-31 LA)
	100 EVO (24-33 LA)
	101 EVO (23-34), 102 (22-35), 103 (21-36)
	116 (8-50)
"""

def barrelDefinition():
	barrel_threshold = {
		98: [26,30],
		99: [25,31],
	}
	evo = 100
	minLA, maxLA = 24, 33

	while evo <= 116:
		#print(evo, minLA, maxLA)
		barrel_threshold[evo] = [minLA, maxLA]
		minLA -= 1
		maxLA += 1
		evo += 1

	print(barrel_threshold)

def convertBPPTeam(team):
	team = team.lower()
	if team == "was":
		return "wsh"
	return team

def writeMostLikely(date):
	with open("static/mlb/schedule.json") as fh:
		schedule = json.load(fh)

	games = [x["game"] for x in schedule[date]]
	teamGame = {}
	for game in games:
		a,h = map(str, game.split(" @ "))
		teamGame[a] = game
		teamGame[h] = game

	url = "https://www.ballparkpal.com/Most-Likely.php"
	likely = nested_dict()

	soup = BS(open("static/bpp/likely.html"), "html.parser")
	for row in soup.select("#batterTable tr")[1:]:
		team = convertBPPTeam(row.select("td[data-column=team]")[0].text.lower())
		game = teamGame.get(team, "")
		player = parsePlayer(row.select("td[data-column=entity]")[0].text.lower())
		prob = parsePlayer(row.select("td[data-column=probability0]")[0].text.lower())
		odds = parsePlayer(row.select("td[data-column=book0]")[0].text.lower())
		likely[game][player]["implied"] = prob
		likely[game][player]["odds"] = odds

	with open("static/bpp/likely.json", "w") as fh:
		json.dump(likely, fh, indent=4)

def writeStrikeouts():
	js = """
	{
		let data = {};
		let rows = Array.from(document.querySelectorAll("#pitcherTable tr")).slice(1);
		for (row of rows) {
			let team = row.querySelector("td").innerText.toLowerCase().replace("was", "wsh");
			let player = row.querySelector("a").innerText.toLowerCase();

			data[team] = {};
			data[team][player] = {};
			data[team][player]["proj"] = parseFloat(row.querySelector("td[data-column=strikeouts]").innerText);
			data[team][player]["line"] = parseFloat(row.querySelector("td[data-column=betLine]").innerText);
			data[team][player]["bpp"] = parseInt(row.querySelector("td[data-column=book0]").innerText);

			for (i = 0; i <= 10; ++i) {
				data[team][player][i.toString()] = parseFloat(row.querySelector(`td[data-column=strikeouts${i}]`).innerText);
			}
		}

		console.log(data);
	}
"""

	with open("static/bpp/strikeouts.json") as fh:
		strikeouts = json.load(fh)

	with open("static/baseballreference/roster.json") as fh:
		roster = json.load(fh)

	with open("static/mlb/schedule.json") as fh:
		schedule = json.load(fh)

	games = [x["game"] for x in schedule[str(datetime.now())[:10]]]
	teamGame = {}
	for game in games:
		a,h = map(str, game.split(" @ "))
		teamGame[a] = game
		teamGame[h] = game

	data = nested_dict()
	for team, pitcherData in strikeouts.items():
		game = teamGame[team]
		playersMap = {}
		for player in roster[team]:
			playersMap[player[0]+". "+player.split(" ")[-1]] = player

		player = list(pitcherData.keys())[0]
		pitcherData = pitcherData[player]
		last = parsePlayer(player).split(" ")[-1].split("-")[-1]
		p = player.split(" ")[0]+" "+last
		p = p.lower()
		player = playersMap.get(p, player)
		data[game][player] = pitcherData.copy()

		"""
		"c. sanchez": {
	      "0": 0.01,
	      "1": 0.02,
	      "2": 0.05,
	      "3": 0.09,
	      "4": 0.13,
	      "5": 0.17,
	      "6": 0.16,
	      "7": 0.14,
	      "8": 0.11,
	      "9": 0.07,
	      "10": 0.04,
	      "proj": 5.83,
	      "line": 5.5,
	      "bpp": -116
	    }
	    """
		over = 0
		for i in range(11):
			over += pitcherData[str(i)]
			data[game][player][f"ou{float(i) + 0.5}"] = over

		for i in range(11):
			k = f"ou{float(i) + 0.5}"
			under = round(data[game][player][k], 2)
			over = round(data[game][player]["ou10.5"] - under, 2)
			data[game][player][k] = f"{over}%/{under}%".replace("0.", "")

	with open("static/bpp/strikeouts.json", "w") as fh:
		json.dump(data, fh, indent=4)

def writeProjections():

	js = """
	{
		let imgs = document.querySelectorAll("img");
		let away = imgs[0].src.split("/").at(-1).split("-")[0];
		let home = imgs[2].src.split("/").at(-1).split("-")[0];
		let game = `${away} @ ${home}`;

		if (data[game]) {
			game = `${away}-gm2 @ ${home}-gm2`;
		}

		game = game.replace("was", "wsh");

		data[game] = {};

		const tables = Array.from(document.querySelectorAll(".boxScoreTable")).slice(2);
		for (table of tables) {
			for (row of Array.from(table.querySelectorAll("tr")).slice(1)) {
				const player = row.querySelector("a").innerText;
				const hr = Array.from(row.querySelectorAll("td")).at(-2).innerText;
				data[game][player] = parseFloat(hr);
			}
		}

		console.log(data);
	}
"""

	with open("static/bpp/projections.json") as fh:
		projections = json.load(fh)

	with open("static/baseballreference/roster.json") as fh:
		roster = json.load(fh)

	with open("static/mlb/schedule.json") as fh:
		schedule = json.load(fh)

	data = nested_dict()

	for game, players in projections.items():
		a,h = map(str, game.split(" @ "))
		playersMap = {}
		for t in [a,h]:
			for player in roster[t]:
				playersMap[player[0]+". "+player.split(" ")[-1]] = player
		
		for player, hr in players.items():
			last = parsePlayer(player).split(" ")[-1].split("-")[-1]
			p = player.split(" ")[0]+" "+last
			p = p.lower()
			print(player, p)
			player = playersMap.get(p, player)
			data[game][player] = hr

	with open("static/bpp/projections.json", "w") as fh:
		json.dump(data, fh, indent=4)

def writeHomeRunZone(date):
	url = "https://www.ballparkpal.com/Home-Run-Zone.php"
	zone = nested_dict()

	soup = BS(open("static/bpp/zone.html"), "html.parser")

	rows = soup.select(".gameSummaryTable")[0].find_all("tr")[1:]
	for row in rows:
		tds = row.find_all("td")
		away = convertMLBTeam(tds[-5].text.lower())
		home = convertMLBTeam(tds[-2].text.lower())
		game = f"{away} @ {home}"
		gameHR = round(float(tds[-4].text) + float(tds[-1].text), 2)
		zone[away] = float(tds[-4].text)
		zone[home] = float(tds[-1].text)
		zone[game] = gameHR

	with open("static/bpp/zone.json", "w") as fh:
		json.dump(zone, fh, indent=4)

def writeParkFactors(date, history):
	url = "https://www.ballparkpal.com/Park-Factors.php"
	factors = nested_dict()

	soup = BS(open("static/bpp/factors.html"), "html.parser")

	games = soup.select(f"td[data-column=Game]")
	arr = [("hr", "HomeRuns"), ("2b/3b", "DoublesTriples"), ("1b", "Singles"), ("r", "Runs")]
	teamGame = {}
	for prop, colName in arr:
		cols = soup.select(f"td[data-column={colName}]")
		seenGame = {}
		for game, col in zip(games, cols):
			roofClosed = len(game.select("img[src*=RoofClosed]")) > 0
			game = game.find("a", class_="gameLink").text.lower()
			words = [x for x in game.split(" ") if x]
			game = " ".join(words)
			a,h = map(str, game.split(" @ "))
			a = convertBPPTeam(a)
			h = convertBPPTeam(h)
			game = f"{a} @ {h}"
			seen = seenGame.get(game, False)
			if game in seenGame:
				game += "-gm2"
			else:
				seenGame[game] = True
				teamGame[a] = game
				teamGame[h] = game
			factors[game]["roof"] = roofClosed
			factors[game][prop] = col.text

	for rows in soup.select("#table_id tbody tr"):
		tds = rows.select("td")
		team = convertBPPTeam(tds[0].text.lower().strip())
		game = teamGame.get(team, "")
		player = parsePlayer(tds[1].text)

		i = 3
		for k in ["hr", "2b/3b", "1b"]:
			factor = tds[i].text
			factorColor = tds[i].get("style").split("; ")[1].split(": ")[-1]

			factors[game]["players"][player][k] = factor
			if not history:
				factors[game]["players"][player][k+"-color"] = factorColor
			i += 1

	winds = soup.select("td[data-column=WindForecast1]")
	for wind in winds:
		game = wind.find_previous("a").text.lower()
		words = [x for x in game.split(" ") if x]
		game = " ".join(words)
		a,h = map(str, game.split(" @ "))
		game = f"{convertBPPTeam(a)} @ {convertBPPTeam(h)}"
		#factors[game]["wind"] = wind

	with open("static/bpp/factors_historical.json") as fh:
		hist = json.load(fh)
	hist[date] = factors
	with open("static/bpp/factors_historical.json", "w") as fh:
		json.dump(hist, fh)
	if not history:
		with open("static/bpp/factors.json", "w") as fh:
			json.dump(factors, fh, indent=4)

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument("--date", "-d")
	parser.add_argument("--likely", action="store_true")
	parser.add_argument("--factors", action="store_true")
	parser.add_argument("--zone", action="store_true")
	parser.add_argument("--update", "-u", action="store_true")
	parser.add_argument("--commit", "-c", action="store_true")
	parser.add_argument("--history", action="store_true")
	parser.add_argument("--tmrw", action="store_true")
	parser.add_argument("--proj", action="store_true")
	parser.add_argument("--projections", "-p", action="store_true")
	parser.add_argument("--strikeouts", "-k", action="store_true")

	args = parser.parse_args()

	date = args.date
	if args.tmrw:
		date = str(datetime.now() + timedelta(days=1))[:10]
	elif not date:
		date = str(datetime.now())[:10]

	if args.factors:
		writeParkFactors(date, args.history)

	if args.likely:
		writeMostLikely(date)

	if args.zone:
		writeHomeRunZone(date)

	if args.update:
		writeParkFactors(date, args.history)

	if args.projections or args.proj:
		writeProjections()

	if args.strikeouts:
		writeStrikeouts()

	if args.commit:
		commitChanges()

	#barrelDefinition()