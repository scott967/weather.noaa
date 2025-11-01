# -*- coding: utf-8 -*-
# from __future__ import unicode_literals

# from future import standard_library
# standard_library.install_aliases()

import datetime
import glob
import os
import re
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
# from lib.utils import FtoC, CtoF, log, ADDON, LANGUAGE, MAPSECTORS, LOOPSECTORS, MAPTYPES
# from lib.utils import WEATHER_CODES, FORECAST, WIND_DIR, SPEEDUNIT, zip_x
# from lib.utils import FEELS_LIKE_F_MPH, FEELS_LIKE_C_KPH, WIND_CHILL_F_MPH, WIND_CHILL_C_KPH, HEAT_INDEX_F, HEAT_INDEX_C
# from lib.utils import get_url_JSON, get_url_image
# from lib.utils import get_datestr, get_timestamp, get_weekday, get_time
from dateutil.parser import parse

from lib.utils import *
from lib.python_metar.metar.Metar import Metar

#    WEATHER_WINDOW  = xbmcgui.Window(12600)
ADDON = xbmcaddon.Addon()
WEATHER_ICON = xbmcvfs.translatePath('%s.png')
DATEFORMAT = xbmc.getRegion('dateshort')
TIMEFORMAT = xbmc.getRegion('meridiem')
MAXDAYS = 14
TEMPUNIT = xbmc.getRegion('tempunit')
SOURCEPREF = ADDON.getSetting("DataSourcePreference")


def set_property(name: str, value: str):
    xbmcgui.Window(12600).setProperty(name, value)


def clear_property(name: str):
    xbmcgui.Window(12600).clearProperty(name)


def code_from_icon(icon:str) -> tuple[str, int]:
    if icon:
        # xbmc.log('icon: %s' % (icon) ,level=xbmc.LOGDEBUG)

        daynight = "day"

        # special handling of forecast.weather.gov "dualimage" icon generator urls
        # https://forecast.weather.gov/DualImage.php?i=bkn&j=shra&jp=30
        # https://forecast.weather.gov/DualImage.php?i=shra&j=bkn&ip=30
        if 'DualImage' in icon:
            # xbmc.log('icon: %s' % icon,level=xbmc.LOGERROR)

            params = icon.split("?")[1].split("&")
            # xbmc.log('params: %s' % params,level=xbmc.LOGERROR)

            code = "day"
            rain = None
            for param in params:
                # xbmc.log('param: %s' % param,level=xbmc.LOGERROR)

                thing = param.split("=")
                p = thing[0]
                v = thing[1]
                xbmc.log(f'p: {p}', level=xbmc.LOGERROR)
                xbmc.log(f'v: {v}', level=xbmc.LOGERROR)
                if p == "i":
                    code = f"day/{v}"
                if p in ("ip", "jp"):
                    if(not rain) or (v > rain):
                        rain = v
#            xbmc.log('code: %s' % code,level=xbmc.LOGERROR)
#            xbmc.log('rain: %s' % rain,level=xbmc.LOGERROR)

            return code, int(rain) if rain else 0

        if '?' in icon:
            icon = icon.rsplit('?', 1)[0]

        # strip off file extension if we have one
        icon = icon.replace(".png", "")
        icon = icon.replace(".jpg", "")

        if "/day/" in icon:
            daynight = "day"
        elif "/night/" in icon:
            daynight = "night"

        rain = None
        code = None
        # loop though our "split" icon paths, and get max rain percent
        # take last icon code in the process
        for checkcode in icon.rsplit('/'):
            thing = checkcode.split(",")
            code = f"{daynight}/{thing[0]}"

            if len(thing) > 1:
                train = thing[1]
                if rain is None or train > rain:
                    rain = train

            # forcast.gov urls may have codes like sct30, which means "scattered clouds 30% chance of rain" ,so regex for it
            cresult = re.search(r"([a-z]+)(\d*)", thing[0])
            if cresult and cresult.group(1):
                code = f"{daynight}/{cresult.group(1)}"
            if cresult and cresult.group(2):
                train = f"{cresult.group(2)}"
                if rain is None or train > rain:
                    rain = train

#        xbmc.log('code: %s' % code,level=xbmc.LOGERROR)
#        xbmc.log('rain: %s' % rain,level=xbmc.LOGERROR)

        return code if code else '', int(rain) if rain else 0
    return '', 0


class Noaa:

    def clear(self):
        set_property('Current.Condition', 'N/A')
        set_property('Current.Temperature', '0')
        set_property('Current.Wind', '0')
        set_property('Current.WindDirection', 'N/A')
        set_property('Current.Humidity', '0')
        set_property('Current.FeelsLike', '0')
        set_property('Current.UVIndex', '0')
        set_property('Current.DewPoint', '0')
        set_property('Current.OutlookIcon', 'na.png')
        set_property('Current.FanartCode', '0')
        for count in range(0, MAXDAYS+1):
            set_property(f'Day{count}.Title', 'N/A')
            set_property(f'Day{count}.HighTemp', '0')
            set_property(f'Day{count}.LowTemp', '0')
            set_property(f'Day{count}.Outlook', 'N/A')
            set_property(f'Day{count}.OutlookIcon', 'na.png')
            set_property(f'Day{count}.FanartCode', '0')

    def refresh_locations(self):
        """sets weather window location property from settings
        """
        locations = 0
        for count in range(1, 6):
            LatLong = ADDON.getSetting(f'Location{count}LatLong')
            loc_name = ADDON.getSetting(f'Location{count}')
            if LatLong:
                locations += 1
                if not loc_name:
                    loc_name = f'Location {count}'
                set_property(f'Location{count}', loc_name)

            else:
                set_property(f'Location{count}', '')

            # set_property('Location%s' % count, loc_name)

        set_property('Locations', str(locations))
        log(f'available locations: {locations}')

    def get_lat_long_by_address(self, num):

        dialog = xbmcgui.Dialog()
        saddress = dialog.input(heading=LANGUAGE(
            32345), defaultt='', type=xbmcgui.INPUT_ALPHANUM)
        saddress = saddress.replace(" ", "+")
        url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=%s&benchmark=4&format=json" % (
            saddress)

        data = get_url_JSON(url)

        # xbmc.log('DEBUG data== %s' % data,level=xbmc.LOGERROR)

        if data and 'result' in data and 'addressMatches' in data['result'] and len(data['result']['addressMatches']) > 0:
            addresslist = []
            addresses = {}
            for count, item in enumerate(data['result']['addressMatches']):
                locx = round(item['coordinates']['x'], 4)
                locy = round(item['coordinates']['y'], 4)
                locfull = f'{locy},{locx}'
                address = item['matchedAddress']
                addresslist.append(address)
                addresses[address] = locfull

            dialog = xbmcgui.Dialog()
            i = dialog.select(LANGUAGE(32348), addresslist)
            # clean up reference to dialog object
            del dialog
            if i >= 0:
                LatLong = addresses[addresslist[i]]
                ADDON.setSetting(f"Location{num}Address", addresslist[i])
                ADDON.setSetting(f"Location{num}LatLong", LatLong)
                self.get_Stations(num, LatLong, True)
        else:
            dialog = xbmcgui.Dialog()
            dialog.ok(heading=LANGUAGE(32346), message=LANGUAGE(32347))
            del dialog
        return

    ########################################################################################
    # Dialog for getting Latitude and Longitude
    ########################################################################################

    def enterLocation(self, num):
        # log("argument: %s" % (sys.argv[1]))

        text = ADDON.getSetting(f"Location{num}LatLong")
        Latitude = ""
        Longitude = ""
        if text and "," in text:
            thing = text.split(",")
            Latitude = thing[0]
            Longitude = thing[1]

        dialog = xbmcgui.Dialog()

        Latitude = dialog.input(
            LANGUAGE(32341), defaultt=Latitude, type=xbmcgui.INPUT_ALPHANUM)

        if not Latitude:
            ADDON.setSetting(f"Location{num}LatLong", "")
            return False

        Longitude = dialog.input(heading=LANGUAGE(32342),
                                 defaultt=Longitude,
                                 type=xbmcgui.INPUT_ALPHANUM)

        if not Longitude:
            ADDON.setSetting(f"Location{num}LatLong", "")
            return False
        LatLong = f"{Latitude},{Longitude}"
        ADDON.setSetting(f"Location{num}LatLong", LatLong)
        self.get_Stations(num, LatLong, True)
        return

    ########################################################################################
    # fetches location data (weather grid point, station, etc, for lattitude,logngitude
    # returns url for fetching local weather stations
    ########################################################################################

    def get_Points(self, num, LatLong, resetName=False):

        prefix = "Location"+num
        log(f'searching for location: {LatLong}')
        url = f'https://api.weather.gov/points/{LatLong}'
        log("url:"+url)
        data = get_url_JSON(url)
        log(f'location data: {data}')
        if not data:
            log('failed to retrieve location data')
            return None
        if data and 'properties' in data:

            if resetName:
                city = data['properties']['relativeLocation']['properties']['city']
                state = data['properties']['relativeLocation']['properties']['state']
                locationName = city+", "+state
                ADDON.setSetting(prefix, locationName)

            gridX = data['properties']['gridX']
            ADDON.setSetting(prefix+'gridX', str(gridX))

            gridY = data['properties']['gridY']
            ADDON.setSetting(prefix+'gridY', str(gridY))

            cwa = data['properties']['cwa']
            ADDON.setSetting(prefix+'cwa',    cwa)

            forecastZone = data['properties']['forecastZone']
            zone = forecastZone.rsplit('/', 1)[1]
            ADDON.setSetting(prefix+'Zone',    zone)

            forecastCounty = data['properties']['county']
            county = forecastCounty.rsplit('/', 1)[1]
            ADDON.setSetting(prefix+'County', county)

            forecastGridData_url = data['properties']['forecastGridData']
            ADDON.setSetting(prefix+'forecastGrid_url', forecastGridData_url)

            forecastHourly_url = data['properties']['forecastHourly']
            ADDON.setSetting(prefix+'forecastHourly_url', forecastHourly_url)

            forecast_url = data['properties']['forecast']
            ADDON.setSetting(prefix+'forecast_url',    forecast_url)

            radarStation = data['properties']['radarStation']
            ADDON.setSetting(prefix+'radarStation',    radarStation)

            # current_datetime = parse("now")
            current_datetime = datetime.datetime.now()
            ADDON.setSetting(prefix+'lastPointsCheck',
                             str(current_datetime))

            stations_url = data['properties']['observationStations']
            return stations_url

    ########################################################################################
    # fetches location data (weather grid point, station, etc, for lattitude,logngitude
    ########################################################################################

    def get_Stations(self, num, LatLong, resetName=False):

        prefix = "Location"+num
        odata = None
        stations_url = self.get_Points(num, LatLong, resetName)
        if stations_url:
            odata = get_url_JSON(stations_url)

        if odata and 'features' in odata:
            stations = {}
            stationlist = []

            for count, item in enumerate(odata['features']):
                stationId = item['properties']['stationIdentifier']
                stationName = item['properties']['name']
                stationlist.append(stationName)
                stations[stationName] = stationId

            dialog = xbmcgui.Dialog()
            i = dialog.select(LANGUAGE(32331), stationlist)
            # clean up reference to dialog object
            del dialog

            ADDON.setSetting(prefix+'Station', stations[stationlist[i]])
            ADDON.setSetting(prefix+'StationName', stationlist[i])

    ########################################################################################
    # fetches daily weather data
    ########################################################################################

    def get_metar(self, station:str) ->str:
        """_summary_Gets current METAR as raw data from an airport reporting station

        Args:
            station (str): The airport 4-alphanum ICAO
        Returns:
            str: the raw METAR
        """
        url = f'https://aviationweather.gov/api/data/metar?ids={station}&format=json'
        current_metar:list[dict] = get_url_JSON(url)
        return current_metar[0].get('rawOb', '')


    def fetchDaily(self, num):

        log(f"SOURCEPREF: {SOURCEPREF}")
        url = ADDON.getSetting(f'Location{num}forecast_url')
        if "preview-api.weather.gov" == SOURCEPREF:
            url = url.replace("https://api.weather.gov",
                              "https://preview-api.weather.gov")

        if 'F' in TEMPUNIT:
            url = f"{url}?units=us"
        elif 'C' in TEMPUNIT:
            url = f"{url}?units=si"

        log(f'forecast url: {url}')

        daily_weather = get_url_JSON(url)

        if daily_weather and 'properties' in daily_weather:
            data = daily_weather['properties']
        else:
            # api.weather.gov is acting up, so fall back to alternate api
            xbmc.log(
                f'failed to find weather data from : {url}', level=xbmc.LOGERROR)
            xbmc.log(f'{daily_weather}', level=xbmc.LOGERROR)
            return self.fetchAltDaily(num)

        for count, item in enumerate(data['periods'], start=0):
            icon:str = item['icon']
            # https://api.weather.gov/icons/land/night/ovc?size=small
            if icon and '?' in icon:
                icon = icon.rsplit('?', 1)[0]
            code, rain = code_from_icon(icon)

            weathercode = WEATHER_CODES.get(code,'31')
            starttime = item['startTime']
            startstamp = get_timestamp(starttime)
            set_property(f'Day{count}.isDaytime', str(item['isDaytime']))
            set_property(f'Day{count}.Title', item['name'])

            if count == 0:  #use first forecast period for current chance of rain
                rain:int = item['probabilityOfPrecipitation']['value']
                set_property('Current.ChancePrecipitation', str(rain))
                set_property('Current.Precipitation', str(rain))
                log(f'First period chance precip is {rain}')
                set_property('Daily.1.DetailedForecast', item.get('detailedForecast', '').replace('/n', ' '))

            if item['isDaytime']:
                # Since we passed units into api, we may need to convert to C, or may not
                if 'F' in TEMPUNIT:
                    set_property(f'Day{count}.HighTemp', str(
                        int(round(FtoC(item['temperature'])))))
                    set_property(f'Day{count}.LowTemp', str(
                        int(round(FtoC(item['temperature'])))))
                    if count in [0,1]:
                        log(f'item {pp(item)} period {count} Daytime temp is {item['temperature']}')
                        set_property('Today.HighTemperature', f"{item['temperature']:.1f}")
                elif 'C' in TEMPUNIT:
                    set_property(f'Day{count}.HighTemp', str(
                        int(round(item['temperature']))))
                    set_property(f'Day{count}.LowTemp', str(
                        int(round(item['temperature']))))
                    if count in [0,1]:
                        log(f'item {pp(item)} period {count} Daytime temp is {item['temperature']}')
                        set_property('Today.HighTemperature', f"{item['temperature']:.1f}")
            if not item['isDaytime']:
                if 'F' in TEMPUNIT:
                    set_property(f'Day{count}.HighTemp', str(
                        int(round(FtoC(item['temperature'])))))
                    set_property(f'Day{count}.LowTemp', str(
                        int(round(FtoC(item['temperature'])))))
                    if count in [0,1]:
                        log(f'item {pp(item)} period {count} Nitetime temp is {int(round(FtoC(item['temperature'])))}')
                        set_property('Today.LowTemperature', f"{item['temperature']:.1f}")
                elif 'C' in TEMPUNIT:
                    set_property(f'Day{count}.HighTemp', str(
                        int(round(item['temperature']))))
                    set_property(f'Day{count}.LowTemp', str(
                        int(round(item['temperature']))))
                    if count in [0,1]:
                            log(f'item {pp(item)} period {count} Nitetime temp is {int(round(item['temperature']))}')
                            set_property('Today.LowTemperature', f"{item['temperature']:.1f}")
            set_property(f'Day{count}.Outlook', item['shortForecast'])
            set_property(f'Day{count}.FanartCode', weathercode)
            set_property(f'Day{count}.OutlookIcon', WEATHER_ICON % weathercode)
            set_property(f'Day{count}.RemoteIcon', icon)

            # NOTE: Day props are 0 based, but Daily/Hourly are 1 based
            set_property(f'Daily.{count+1}.isDaytime', str(item['isDaytime']))
            set_property(f'Daily.{count+1}.Outlook', item['shortForecast'])
            set_property(f'Daily.{count+1}.ShortOutlook',
                         item['shortForecast'])
            set_property(f'Daily.{count+1}.DetailedOutlook',
                         item['detailedForecast'])

            set_property(f'Daily.{count+1}.RemoteIcon', icon)
            set_property(f'Daily.{count+1}.OutlookIcon',
                         WEATHER_ICON % weathercode)
            set_property(f'Daily.{count+1}.FanartCode', weathercode)
            set_property(f'Daily.{count+1}.WindDirection',
                         item['windDirection'])
            set_property(f'Daily.{count+1}.WindSpeed', item['windSpeed'])

            if item['isDaytime']:
                set_property(f'Daily.{count+1}.LongDay', item['name'])
                set_property(f'Daily.{count+1}.ShortDay',
                             get_weekday(startstamp, 's')+" (d)")
                # set_property(f'Daily.{count+1}.TempDay', u'%i\N{DEGREE SIGN}%s' % (item['temperature'], item['temperatureUnit']))
                # set_property(f'Daily.{count+1}.HighTemperature', u'%i\N{DEGREE SIGN}%s' % (item['temperature'], item['temperatureUnit']))

                # we passed units to api, so we got back C or F, so don't need to convert
                set_property(f'Daily.{count+1}.TempDay',
                             f'{item["temperature"]}{TEMPUNIT}')
                set_property(f'Daily.{count+1}.HighTemperature',
                             f'{item["temperature"]}{TEMPUNIT}')
                set_property(f'Daily.{count+1}.TempNight', '')
                set_property(f'Daily.{count+1}.LowTemperature', '')

            if not item['isDaytime']:
                set_property(f'Daily.{count+1}.LongDay', item['name'])
                set_property(f'Daily.{count+1}.ShortDay',
                             get_weekday(startstamp, 's')+" (n)")

                set_property(f'Daily.{count+1}.TempDay', '')
                set_property(f'Daily.{count+1}.HighTemperature', '')
                # we passed units to api, so we got back C or F, so don't need to convert
                set_property(f'Daily.{count+1}.TempNight',
                             f'{item["temperature"]}{TEMPUNIT}')
                set_property(f'Daily.{count+1}.LowTemperature',
                             f'{item["temperature"]}{TEMPUNIT}')

            if DATEFORMAT[1] == 'd' or DATEFORMAT[0] == 'D':
                set_property(f'Daily.{count+1}.LongDate',
                             get_datestr(startstamp, 'dl'))
                set_property(f'Daily.{count+1}.ShortDate',
                             get_datestr(startstamp, 'ds'))
            else:
                set_property(f'Daily.{count+1}.LongDate',
                             get_datestr(startstamp, 'ml'))
                set_property(f'Daily.{count+1}.ShortDate',
                             get_datestr(startstamp, 'ms'))

            rain = 0
            if item['probabilityOfPrecipitation'] and item['probabilityOfPrecipitation']['value']:
                rain:int = item['probabilityOfPrecipitation']['value']

            if rain and str(rain) and "0" != str(rain):
                set_property(f'Daily.{count+1}.Precipitation', str(rain) + '%')
            else:
                # set_property(f'Daily.{count+1}.ChancePrecipitation', '')
                clear_property(f'Daily.{count+1}.Precipitation')

    ########################################################################################
    # fetches daily weather data using alternative api endpoint
    ########################################################################################

    def fetchAltDaily(self, num:str):

        latlong = ADDON.getSetting('Location'+str(num)+"LatLong")
        latitude = latlong.rsplit(',', 1)[0]
        longitude = latlong.rsplit(',', 1)[1]

        url = "https://forecast.weather.gov/MapClick.php?lon=" + \
            longitude+"&lat="+latitude+"&FcstType=json"
        log(f'forecast url: {url}')

        daily_weather = get_url_JSON(url)

        if daily_weather and 'data' in daily_weather:

            dailydata = [
                {"startPeriodName": a,
                 "startValidTime": b,
                 "tempLabel": c,
                 "temperature": d,
                 "pop": e,
                 "weather": f,
                 "iconLink": g,
                 "hazard": h,
                 "hazardUrl": i,
                 "text": j
                 }
                for a, b, c, d, e, f, g, h, i, j in zip_x(None,
                                                          daily_weather['time']['startPeriodName'],
                                                          daily_weather['time']['startValidTime'],
                                                          daily_weather['time']['tempLabel'],
                                                          daily_weather['data']['temperature'],
                                                          daily_weather['data']['pop'],
                                                          daily_weather['data']['weather'],
                                                          daily_weather['data']['iconLink'],
                                                          daily_weather['data']['hazard'],
                                                          daily_weather['data']['hazardUrl'],
                                                          daily_weather['data']['text']
                                                          )]

        else:
            xbmc.log(
                f'failed to retrieve weather data from : {url}', level=xbmc.LOGERROR)
            xbmc.log(f'{daily_weather}', level=xbmc.LOGERROR)
            return None

        for count, item in enumerate(dailydata, start=0):
            icon = item['iconLink']

            # https://api.weather.gov/icons/land/night/ovc?size=small
            code, ignoreme = code_from_icon(icon)
            weathercode = WEATHER_CODES.get(code)

            starttime = item['startValidTime']
            startstamp = get_timestamp(starttime)
            set_property(f'Day{count}.Title', item['startPeriodName'])

            set_property(f'Day{count}.Outlook', item['weather'])
            set_property(f'Day{count}.Details', item['text'])

            set_property(f'Day{count}.OutlookIcon', WEATHER_ICON % weathercode)
            set_property(f'Day{count}.RemoteIcon', icon)
            if weathercode:
                set_property(f'Day{count}.FanartCode', weathercode)

            # NOTE: Day props are 0 based, but Daily/Hourly are 1 based
            set_property(f'Daily.{count+1}.DetailedOutlook', item['text'])
            set_property(f'Daily.{count+1}.Outlook', item['weather'])
            set_property(f'Daily.{count+1}.ShortOutlook', item['weather'])

            set_property(f'Daily.{count+1}.OutlookIcon',
                         WEATHER_ICON % weathercode)
            set_property(f'Daily.{count+1}.RemoteIcon', icon)
            if weathercode:
                set_property(f'Daily.{count+1}.FanartCode', weathercode)

            if item['tempLabel'] == 'High':
                set_property(f'Daily.{count+1}.LongDay',
                             item['startPeriodName'])
                set_property(f'Daily.{count+1}.ShortDay',
                             get_weekday(startstamp, 's')+" (d)")

                set_property(f'Daily.{count+1}.TempNight', '')
                set_property(f'Daily.{count+1}.LowTemperature', '')
                if 'F' in TEMPUNIT:
                    set_property(f'Daily.{count+1}.TempDay',
                                 f'{int(round(float(item["temperature"])))}{TEMPUNIT}')
                    set_property(f'Daily.{count+1}.HighTemperature',
                                 f'{int(round(float(item["temperature"])))}{TEMPUNIT}')
                elif 'C' in TEMPUNIT:
                    set_property(f'Daily.{count+1}.TempDay',
                                 f'{int(round(FtoC(float(item["temperature"]))))}{TEMPUNIT}')
                    set_property(f'Daily.{count+1}.HighTemperature',
                                 f'{int(round(FtoC(float(item["temperature"]))))}{TEMPUNIT}')

            if item['tempLabel'] == 'Low':
                set_property(f'Daily.{count+1}.LongDay',
                             item['startPeriodName'])
                set_property(f'Daily.{count+1}.ShortDay',
                             get_weekday(startstamp, 's')+" (n)")

                set_property(f'Daily.{count+1}.TempDay', '')
                set_property(f'Daily.{count+1}.HighTemperature', '')
                if 'F' in TEMPUNIT:
                    set_property(f'Daily.{count+1}.TempNight',
                                 f'{int(round(float(item["temperature"])))}{TEMPUNIT}')
                    set_property(f'Daily.{count+1}.LowTemperature',
                                 f'{int(round(float(item["temperature"])))}{TEMPUNIT}')
                elif 'C' in TEMPUNIT:
                    set_property(f'Daily.{count+1}.TempNight',
                                 f'{int(round(FtoC(float(item["temperature"]))))}{TEMPUNIT}')
                    set_property(f'Daily.{count+1}.LowTemperature',
                                 f'{int(round(FtoC(float(item["temperature"]))))}{TEMPUNIT}')

            if DATEFORMAT[1] == 'd' or DATEFORMAT[0] == 'D':
                set_property(f'Daily.{count+1}.LongDate',
                             get_datestr(startstamp, 'dl'))
                set_property(f'Daily.{count+1}.ShortDate',
                             get_datestr(startstamp, 'ds'))
            else:
                set_property(f'Daily.{count+1}.LongDate',
                             get_datestr(startstamp, 'ml'))
                set_property(f'Daily.{count+1}.ShortDate',
                             get_datestr(startstamp, 'ms'))

            rain = item['pop']
            if rain and str(rain) and "0" != str(rain):
                set_property(f'Daily.{count+1}.Precipitation', str(rain) + '%')
            else:
                # set_property(f'Daily.{count+1}.ChancePrecipitation', '')
                clear_property(f'Daily.{count+1}.Precipitation')

        if daily_weather and 'currentobservation' in daily_weather:
            data = daily_weather['currentobservation']
            icon = "http://forecast.weather.gov/newimages/large/%s" % data.get(
                'Weatherimage')
            code, rain = code_from_icon(icon)
            weathercode = WEATHER_CODES.get(code)

            set_property('Current.Location', data.get('name'))
            set_property('Current.RemoteIcon', icon)
            # xbmc translates it to Current.ConditionIcon
            set_property('Current.OutlookIcon', f'{weathercode}.png')
            if weathercode:
                set_property('Current.FanartCode', weathercode)
            set_property('Current.Condition',
                         FORECAST.get(data.get('Weather', ''), ''))
            set_property('Current.Humidity', str(data.get('Relh')))
            set_property('Current.DewPoint', str(
                int(round(FtoC(data.get('Dewp'))))))

            try:
                temp = data.get('Temp')
                set_property('Current.Temperature',
                             str(int(round(FtoC(temp)))))
            except Exception:
                # set_property('Current.Temperature','')
                clear_property('Current.Temperature')

            try:
                set_property('Current.Wind', str(
                    round(float(data.get('Winds'))*1.609298167)))
            except Exception:
                # set_property('Current.Wind','')
                clear_property('Current.Wind')

            try:
                set_property('Current.WindDirection',
                             xbmc.getLocalizedString(WIND_DIR(int(data.get('Windd')))))
            except Exception:
                # set_property('Current.WindDirection', '')
                clear_property('Current.WindDirection')

    #        try:
    #            set_property('Current.WindGust'    , str(SPEED(float(data.get('Gust'))/2.237)) + SPEEDUNIT)
    #        except Exception:
    #            clear_property('Current.WindGust')
    #            ##set_property('Current.WindGust'    , '')

            if rain and str(rain) and "0" != str(rain):
                set_property('Current.Precipitation', str(rain)+'%')
            else:
                clear_property('Current.Precipitation')

            # calculate feels like
            clear_property('Current.FeelsLike')
            try:
                wind = data.get('Winds')
                if not wind:
                    wind = 0
                feelslike = FEELS_LIKE_C_KPH(FtoC(data.get('Temp')),
                                             int(float(wind)/2.237),
                                             int(data.get('Relh')))
                if feelslike:
                    # xbmc.log('feelslike: %s' % (feelslike),level=xbmc.LOGERROR)
                    set_property('Current.FeelsLike',
                                 str(int(round(feelslike))))
                else:
                    clear_property('Current.FeelsLike')
            except Exception:
                clear_property('Current.FeelsLike')
                # set_property('Current.FeelsLike', '')

    #        # if we have windchill or heatindex directly, then use that instead
    #        if data.get('WindChill') and not "NA" == data.get('WindChill'):
    #            set_property('Current.FeelsLike', str(FtoC(data.get('WindChill'))) )
    #        if data.get('HeatIndex') and not "NA" == data.get('HeatIndex'):
    #            set_property('Current.FeelsLike', str(FtoC(data.get('HeatIndex'))) )

    ########################################################################################
    # fetches current weather info for location
    ########################################################################################

    def fetchCurrent(self, num:str):
        station = ADDON.getSetting(f'Location{num}Station')
        url = f"https://api.weather.gov/stations/{station}/observations/latest"
        current:dict[str,str]|list[dict[str,str]] = get_url_JSON(url)
        if current and 'properties' in current:
            data:dict[str,str] = current['properties']
        else:
            xbmc.log(
                f'failed to find weather data from : {url}', level=xbmc.LOGERROR)
            xbmc.log(f'{current}', level=xbmc.LOGERROR)
            return
        parsed_metar = None
        metar_station = data.get('stationId')
        if metar_station:
            metarcode = self.get_metar(metar_station)
            if metarcode:
                parsed_metar = Metar(metarcode).string()
        if not parsed_metar:
            parsed_metar = Metar(data['rawMessage']).string(
            ) if data.get('rawMessage') else 'Not available'
        #log(f'METAR PARSED is {parsed_metar}')
        parsed_metar = parsed_metar.replace('\n', ' / ')
        set_property('Current.METAR', parsed_metar)

        icon:str = data['icon']
        # https://api.weather.gov/icons/land/night/ovc?size=small
        code = None
        rain = None
        if icon:
            if '?' in icon:
                icon = icon.rsplit('?', 1)[0]
            code, rain = code_from_icon(icon)
            weathercode = WEATHER_CODES.get(code, "32")
            set_property('Current.RemoteIcon', icon)
            set_property('Current.OutlookIcon',
                         # xbmc translates it to Current.ConditionIcon
                         f'{weathercode}.png')
            set_property('Current.FanartCode', weathercode)

        set_property('Current.Condition', FORECAST.get(
            data.get('textDescription', '').lower(), data.get('textDescription', '')))
        try:
            set_property('Current.Humidity', str(
                round(data.get('relativeHumidity').get('value'))))
        except Exception:
            # set_property('Current.Humidity'        , '')
            clear_property('Current.Humidity')

        try:
            # temp = int(round(data.get('temperature').get('value')))
            temp:float = data.get('temperature').get('value')
            # api values are in C
            set_property('Current.Temperature', str(temp))
        except Exception:
            # set_property('Current.Temperature','')
            temp = 0
            clear_property('Current.Temperature')
        try:
            # set_property('Current.Wind', str(int(round(data.get('windSpeed').get('value')))))
            set_property('Current.Wind', str(
                data.get('windSpeed').get('value')))
        except Exception:
            # set_property('Current.Wind','')
            clear_property('Current.Wind')

        try:
            set_property('Current.WindDirection',
                         xbmc.getLocalizedString(WIND_DIR(int(round(data.get('windDirection').get('value'))))))
        except Exception:
            # set_property('Current.WindDirection', '')
            clear_property('Current.WindDirection')

        if rain and str(rain) and "0" != str(rain):
            set_property('Current.Precipitation', f'{rain}')
        else:
            # set_property('Current.ChancePrecipitation', '')
            clear_property('Current.Precipitation')

        # set_property('Current.FeelsLike', '')
        clear_property('Current.WindChill')
        clear_property('Current.HeatIndex')
        # calculate feels like
        windspeed:int = data.get('windSpeed').get('value')
        if not windspeed:
            windspeed = 0

        try:
            feelslike = FEELS_LIKE_C_KPH(data.get('temperature').get('value'),
                                         windspeed,
                                         data.get('relativeHumidity').get('value'))
            if feelslike:
                # xbmc.log('feelslike: %s' % (feelslike),level=xbmc.LOGERROR)
                # feels like wants raw celcius value
                set_property('Current.FeelsLike', str(feelslike))
            else:
                set_property('Current.FeelsLike', str(temp))
        except Exception:
            set_property('Current.FeelsLike', str(temp))

        # if we have windchill or heat index directly, then use that instead
        if data.get('windChill').get('value'):
            # xbmc.log('windchill direct: %s' % (str(int(round(data.get('windChill').get('value'))))),level=xbmc.LOGERROR)
            if 'F' in TEMPUNIT:
                set_property('Current.WindChill',
                             f'{int(round(CtoF(data.get("windChill").get("value"))))}{TEMPUNIT}')
            elif 'C' in TEMPUNIT:
                set_property('Current.WindChill',
                             f'{int(round(data.get("windChill").get("value")))}{TEMPUNIT}')
            # feels like wants raw celcius value
            set_property('Current.FeelsLike', str(
                data.get('windChill').get('value')))

        if data.get('heatIndex').get('value'):
            # xbmc.log('windchill direct: %s' % (str(int(round(data.get('heatIndex').get('value'))))),level=xbmc.LOGERROR)
            if 'F' in TEMPUNIT:
                set_property('Current.heatIndex',
                             f'{int(round(CtoF(data.get("heatIndex").get("value"))))}{TEMPUNIT}')
            elif 'C' in TEMPUNIT:
                set_property('Current.heatIndex',
                             f'{int(round(data.get("heatIndex").get("value")))}{TEMPUNIT}')
            # feels like wants raw celcius value
            set_property('Current.FeelsLike', str(
                data.get('heatIndex').get('value')))

        try:
            # temp = int(round(data.get('dewpoint').get('value',0)))
            temp = data.get('dewpoint').get('value')
            set_property('Current.DewPoint', str(temp))  # api values are in C
        except Exception:
            set_property('Current.DewPoint', '')

    # extended properties

    #    try:
    #        set_property('Current.WindGust'    , SPEED(float(data.get('windGust').get('value',0))/3.6) + SPEEDUNIT)
    #    except Exception:
    #        set_property('Current.WindGust'    , '')

        try:
            set_property('Current.SeaLevel',
                f'{data.get("seaLevelPressure").get("value", 0)/100:.1f} mb')  #Pascal to millibar
        except Exception:
            set_property('Current.SeaLevel', '')

        try:
            set_property('Current.GroundLevel',
                f'{data.get("barometricPressure").get("value", 0)/100:.1f} mb')
            set_property('Current.Pressure',
                f'{data.get("barometricPressure").get("value", 0)/100:.1f} mb')
        except Exception:
            set_property('Current.GroundLevel', '')

    ########################################################################################
    # fetches any weather alerts for location
    ########################################################################################

    def fetchWeatherAlerts(self, num:str):

        # we could fetch alerts for either 'County', or 'Zone'
        # https://api.weather.gov/alerts/active/zone/CTZ006
        # https://api.weather.gov/alerts/active/zone/CTC009
        # https://api.weather.gov/alerts/active?status=actual&point=%7Blat%7D,%7Blong%7D

        # for now, lets use the point alert lookup, as suggested by the weather api team

        # a_zone = ADDON.getSetting('Location'+str(num)+'County')
        # url="https://api.weather.gov/alerts/active/zone/%s" %a_zone

        # we are storing lat,long as comma separated already, so that is convienent for us and we can just drop it into the url
        latlong = ADDON.getSetting('Location'+str(num)+'LatLong')
        url = f"https://api.weather.gov/alerts/active?status=actual&point={latlong}"

        # if 'F' in TEMPUNIT:
        #    url="%s&units=us" % url
        # elif 'C' in TEMPUNIT:
        #    url="%s&units=si" % url

        alerts:dict = get_url_JSON(url)
        # if we have a valid response then clear our current alerts
        if alerts and 'features' in alerts:
            for count in range(1, 10):
                clear_property(f'Alerts.{count}.event')
        else:
            xbmc.log(
                f'failed to get proper alert response {url}', level=xbmc.LOGERROR)
            xbmc.log(f'{alerts}', level=xbmc.LOGDEBUG)
            return

        if 'features' in alerts and alerts['features']:
            data = alerts['features']
            set_property('Alerts.IsFetched', 'true')
        else:
            clear_property('Alerts.IsFetched')
            xbmc.log(
                f'No current weather alerts from {url}', level=xbmc.LOGDEBUG)
            return

        for count, item in enumerate(data, start=1):

            thisdata = item['properties']
            set_property(f'Alerts.{count}.status', str(thisdata['status']))
            set_property(f'Alerts.{count}.messageType',
                         str(thisdata['messageType']))
            set_property(f'Alerts.{count}.category', str(thisdata['category']))
            set_property(f'Alerts.{count}.severity', str(thisdata['severity']))
            set_property(f'Alerts.{count}.certainty',
                         str(thisdata['certainty']))
            set_property(f'Alerts.{count}.urgency', str(thisdata['urgency']))
            set_property(f'Alerts.{count}.event', str(thisdata['event']))
            set_property(f'Alerts.{count}.headline', str(thisdata['headline']))
            set_property(f'Alerts.{count}.description',
                         str(thisdata['description']))
            set_property(f'Alerts.{count}.instruction',
                         str(thisdata['instruction']))
            set_property(f'Alerts.{count}.response', str(thisdata['response']))

    ########################################################################################
    # fetches hourly weather data
    ########################################################################################

    def fetchHourly(self, num: str):
        """sets weather window properties for hourly forecast

        Args:
            num (int): location number 1-3
        """

        log(f"SOURCEPREF: {SOURCEPREF}")

        url = ADDON.getSetting('Location'+str(num)+'forecastHourly_url')
        if "preview-api.weather.gov" == SOURCEPREF:
            url = url.replace("https://api.weather.gov",
                              "https://preview-api.weather.gov")
            log(f"url-x: {url}")

        if 'F' in TEMPUNIT:
            url = f"{url}?units=us"
        elif 'C' in TEMPUNIT:
            url = f"{url}?units=si"

        hourly_weather = get_url_JSON(url)
        if hourly_weather and 'properties' in hourly_weather:
            data = hourly_weather['properties']
        else:
            xbmc.log(
                f'failed to find proper hourly weather from {url}', level=xbmc.LOGERROR)
            return
        # api is currently returning a 0 % rain icon url, which is not valid, so need to clean it
        iconreplacepattern1 = re.compile(r"[,]0$")

    # extended properties
        for count, item in enumerate(data['periods'], start=0):

            icon = item['icon']
            # https://api.weather.gov/icons/land/night/ovc?size=small
            if icon:
                if '?' in icon:
                    icon = icon.rsplit('?', 1)[0]
                code, rain = code_from_icon(icon)
                icon = iconreplacepattern1.sub("", icon)
            set_property(f'Hourly.{count+1}.RemoteIcon', icon)

            weathercode = WEATHER_CODES.get(code)
            starttime = item['startTime']
            startstamp = get_timestamp(starttime)
            if DATEFORMAT[1] == 'd' or DATEFORMAT[0] == 'D':
                set_property(f'Hourly.{count+1}.LongDate',
                             get_fulldatestr(startstamp, 'dl'))
                set_property(f'Hourly.{count+1}.ShortDate',
                             get_fulldatestr(startstamp, 'ds'))
            else:
                set_property(f'Hourly.{count+1}.LongDate',
                             get_fulldatestr(startstamp, 'ml'))
                set_property(f'Hourly.{count+1}.ShortDate',
                             get_fulldatestr(startstamp, 'ms'))

            set_property(f'Hourly.{count+1}.Time', get_time(startstamp))
            if DATEFORMAT[1] == 'd' or DATEFORMAT[0] == 'D':
                set_property(f'Hourly.{count+1}.LongDate',
                             get_fulldatestr(startstamp, 'dl'))
                set_property(f'Hourly.{count+1}.ShortDate',
                             get_fulldatestr(startstamp, 'ds'))
            else:
                set_property(f'Hourly.{count+1}.LongDate',
                             get_fulldatestr(startstamp, 'ml'))
                set_property(f'Hourly.{count+1}.ShortDate',
                             get_fulldatestr(startstamp, 'ms'))

            set_property(f'Hourly.{count+1}.Outlook',
                         FORECAST.get(item['shortForecast'], ''))
            set_property(f'Hourly.{count+1}.ShortOutlook',
                         FORECAST.get(item['shortForecast'], ''))
            set_property(f'Hourly.{count+1}.OutlookIcon',
                         WEATHER_ICON % weathercode)
            set_property(f'Hourly.{count+1}.FanartCode', weathercode)
            windspeed = item['windSpeed']

            if windspeed and (windspeed == "0 mph" or windspeed == "0 km/h"):
                windspeed = ""

            if windspeed and item['windDirection']:
                set_property(
                    f'Hourly.{count+1}.WindDirection', item['windDirection'])
                set_property(f'Hourly.{count+1}.WindSpeed', windspeed)
            else:
                clear_property(f'Hourly.{count+1}.WindDirection')
                clear_property(f'Hourly.{count+1}.WindSpeed')

            # set_property(f'Hourly.{count+1}.Temperature',    str(item['temperature'])+u'\N{DEGREE SIGN}'+item['temperatureUnit'])

            # we passed units to api, so we got back C or F, so don't need to convert
            set_property(f'Hourly.{count+1}.Temperature',
                         f'{int(round(item['temperature']))}{TEMPUNIT}')
            # if 'F' in TEMPUNIT:
            # set_property(f'Hourly.{count+1}.Temperature', '%s%s' % (item['temperature'], TEMPUNIT))
            # elif 'C' in TEMPUNIT:
            # set_property(f'Hourly.{count+1}.Temperature', '%s%s' % (FtoC(item['temperature']), TEMPUNIT))

            rain = 0
            if item['probabilityOfPrecipitation'] and item['probabilityOfPrecipitation']['value']:
                rain = item['probabilityOfPrecipitation']['value']

            if rain and str(rain) and "0" != str(rain):
                set_property(
                    f'Hourly.{count+1}.Precipitation', str(rain) + '%')
            else:
                clear_property(f'Hourly.{count+1}.Precipitation')

            humid = 0
            if item['relativeHumidity'] and item['relativeHumidity']['value']:
                humid = item['relativeHumidity']['value']

            if humid and str(humid) and "0" != str(humid):
                set_property(f'Hourly.{count+1}.Humidity', str(humid) + '%')
            else:
                clear_property(f'Hourly.{count+1}.Humidity')

            dewpoint = 0
            if item['dewpoint'] and item['dewpoint']['value']:
                dewpoint = item['dewpoint']['value']

            if dewpoint and str(dewpoint) and "0" != str(dewpoint):
                # API is always returning dewpoint in C rather then obeying our prefered units, so convert
                if 'F' in TEMPUNIT:
                    set_property(f'Hourly.{count+1}.DewPoint',
                                 '%s%s' % (int(round(CtoF(dewpoint))), TEMPUNIT))
                elif 'C' in TEMPUNIT:
                    set_property(f'Hourly.{count+1}.DewPoint',
                                 '%s%s' % (int(round(dewpoint)), TEMPUNIT))
            else:
                clear_property(f'Hourly.{count+1}.DewPoint')

            if 'F' in TEMPUNIT:
                # xbmc.log('api windspeed %s' % (item['windSpeed']),level=xbmc.LOGERROR)
                windspeed = 0
                if item['windSpeed'] and item['windSpeed'].endswith(" mph"):
                    windspeed = item['windSpeed'].rstrip(" mph")
                # xbmc.log('windspeed %s' % (windspeed),level=xbmc.LOGERROR)
                # xbmc.log('T:%s W:%s H:%s' % (item['temperature'], windspeed, humid),level=xbmc.LOGERROR)

                try:
                    feelslike = FEELS_LIKE_F_MPH(
                        item['temperature'], windspeed, humid)
                    if feelslike:
                        set_property(f'Hourly.{count+1}.FeelsLike',
                                     '%s%s' % (int(round(feelslike)), TEMPUNIT))
                    else:
                        clear_property(f'Hourly.{count+1}.FeelsLike')
                except Exception:
                    # xbmc.log('Error Loading Feels-like %s %s %s' % (item['temperature'], windspeed, humid),level=xbmc.LOGERROR)
                    clear_property(f'Hourly.{count+1}.FeelsLike')
                try:
                    windchill = WIND_CHILL_F_MPH(
                        item['temperature'], windspeed)
                    if windchill:
                        set_property(f'Hourly.{count+1}.WindChill',
                                     '%s%s' % (int(round(windchill)), TEMPUNIT))
                    else:
                        clear_property(f'Hourly.{count+1}.WindChill')
                except Exception:
                    # xbmc.log('Error Loading    %s %s %s' % (item['temperature'], windspeed, humid),level=xbmc.LOGERROR)
                    clear_property(f'Hourly.{count+1}.WindChill')
                try:
                    heatindex = HEAT_INDEX_F(item['temperature'], humid)
                    if heatindex:
                        set_property(f'Hourly.{count+1}.HeatIndex',
                                     '%s%s' % (int(round(heatindex)), TEMPUNIT))
                    else:
                        clear_property(f'Hourly.{count+1}.HeatIndex')
                except Exception:
                    # xbmc.log('Error Loading    %s %s %s' % (item['temperature'], windspeed, humid),level=xbmc.LOGERROR)
                    clear_property(f'Hourly.{count+1}.HeatIndex')
            elif 'C' in TEMPUNIT:
                try:
                    windspeed = 0
                    if item['windSpeed'] and item['windSpeed'].endswith(" km/h"):
                        windspeed = item['windSpeed'].rstrip(" km/h")
                    feelslike = FEELS_LIKE_C_KPH(
                        item['temperature'], windspeed, humid)
                    if feelslike:
                        set_property(f'Hourly.{count+1}.FeelsLike',
                                     f'{int(round(feelslike))}{TEMPUNIT}')
                    else:
                        clear_property(f'Hourly.{count+1}.FeelsLike')
                except Exception:
                    clear_property(f'Hourly.{count+1}.FeelsLike')
                try:
                    windspeed = 0
                    if item['windSpeed'] and item['windSpeed'].endswith(" km/h"):
                        windspeed = item['windSpeed'].rstrip(" km/h")
                    windchill = WIND_CHILL_C_KPH(
                        item['temperature'], windspeed)
                    if windchill:
                        set_property(f'Hourly.{count+1}.WindChill',
                                     f'{int(round(windchill))}{TEMPUNIT}')
                    else:
                        clear_property(f'Hourly.{count+1}.WindChill')
                except Exception:
                    # xbmc.log('Error Loading    %s %s %s' % (item['temperature'], windspeed, humid),level=xbmc.LOGERROR)
                    clear_property(f'Hourly.{count+1}.WindChill')
                try:
                    heatindex = HEAT_INDEX_C(item['temperature'], humid)
                    if heatindex:
                        set_property(f'Hourly.{count+1}.HeatIndex',
                                     f'{int(round(heatindex))}{TEMPUNIT}')
                    else:
                        clear_property(f'Hourly.{count+1}.HeatIndex')
                except Exception:
                    # xbmc.log('Error Loading    %s %s %s' % (item['temperature'], windspeed, humid),level=xbmc.LOGERROR)
                    clear_property(f'Hourly.{count+1}.HeatIndex')

        count = 1

    ########################################################################################
    # Grabs map selection from user in settings
    ########################################################################################

    def mapSettings(self, mapid):
        s_sel = ADDON.getSetting(mapid+"Sector")
        t_sel = ADDON.getSetting(mapid+"Type")

        t_keys = []
        t_values = []

        # 1st option is blank for removing map
        t_keys.append("")
        t_values.append("")

        for key, value in MAPTYPES.items():
            t_keys.append(key)
            t_values.append(value['name'])

        dialog = xbmcgui.Dialog()

        ti = 0
        try:
            ti = t_keys.index(t_sel)
        except Exception:
            ti = 0
        ti = dialog.select(LANGUAGE(32350), t_values, 0, ti)
        t_sel = t_keys[ti]
        ADDON.setSetting(mapid+"Type", t_keys[ti])

        if ti > 0:

            if ("RADAR_LOOP" == t_sel):
                Sectors = LOOPSECTORS
            else:
                Sectors = MAPSECTORS

            # convert our map data into matching arrays to pass into dialog
            s_keys = []
            s_values = []

            for key, value in Sectors.items():
                s_keys.append(key)
                s_values.append(value['name'])

            # grab index of current region, and pass in as default to dialog
            si = 0
            try:
                si = s_keys.index(s_sel.lower())
            except Exception:
                # ignore if we did not find
                si = 0
            si = dialog.select(LANGUAGE(32349), s_values, 0, si)
            s_sel = s_keys[si]
            ADDON.setSetting(mapid+"Sector", s_sel)
            ADDON.setSetting(
                mapid+"Label", Sectors[s_sel]['name']+":"+MAPTYPES[t_sel]['name'])
            ADDON.setSetting(
                mapid+"Select", Sectors[s_sel]['name']+":"+MAPTYPES[t_sel]['name'])
        else:
            ADDON.setSetting(mapid+"Label", "")
            ADDON.setSetting(mapid+"Select", "")

        # clean up referenced dialog object
        del dialog

    ########################################################################################
    # Main Kodi entry point
    ########################################################################################

    def __init__(self):

        log(
            f'version {ADDON.getAddonInfo("version")} started with argv: {sys.argv[1]}')

        set_property('Forecast.IsFetched', 'true')
        set_property('Current.IsFetched', 'true')
        set_property('Today.IsFetched', '')
        set_property('Daily.IsFetched', 'true')
        set_property('Detailed.IsFetched', 'true')
        set_property('Weekend.IsFetched', '')
        set_property('36Hour.IsFetched', '')
        set_property('Hourly.IsFetched', 'true')
        set_property('NOAA.IsFetched', 'true')
        set_property('WeatherProvider', 'NOAA')
        set_property('WeatherProviderLogo',
                     xbmcvfs.translatePath(os.path.join(ADDON.getAddonInfo('path'),
                                                        'resources', 'media', 'skin-banner.png')))

        if sys.argv[1].startswith('EnterLocation'):
            num = sys.argv[2]
            log(f'sys.srg num type: {type(num)}')
            self.enterLocation(num)

        if sys.argv[1].startswith('EnterAddress'):
            num = sys.argv[2]
            log(f'sys.srg num type: {type(num)}')
            self.get_lat_long_by_address(num)

        if sys.argv[1].startswith('FetchLocation'):
            num = sys.argv[2]
            log(f'sys.srg num type: {type(num)}')
            LatLong = ADDON.getSetting("Location"+num+"LatLong")
            if not LatLong:
                self.enterLocation(num)
            elif LatLong:
                self.get_Stations(num, LatLong)

        elif sys.argv[1].startswith('Map'):

            self.mapSettings(sys.argv[1])

        else:

            num = sys.argv[1]
            LatLong = ADDON.getSetting(f'Location{num}LatLong')

            station = ADDON.getSetting(f'Location{num}Station')
            if station == '':
                log(f"calling location with {LatLong}")
                self.get_Stations(f'{num}', LatLong)

            try:
                lastPointsCheck = ADDON.getSetting(
                    f'Location{num}lastPointsCheck')
                last_check = parse(lastPointsCheck)
                current_datetime = datetime.datetime.now()
                next_check = last_check+datetime.timedelta(days=2)
                if (next_check < current_datetime):
                    self.get_Points(f'{num}', LatLong)
            except Exception:
                self.get_Points(f'{num}', LatLong)

            self.refresh_locations()

            LatLong = ADDON.getSetting(f'Location{num}')

            if LatLong:
                self.fetchWeatherAlerts(num)
                if "forecast.weather.gov" == SOURCEPREF:
                    self.fetchAltDaily(num)
                else:
                    self.fetchCurrent(num)
                    self.fetchDaily(num)
                self.fetchHourly(num)
                Station = ADDON.getSetting(f'Location{num}radarStation')

                set_property('Map.IsFetched', 'true')
                # KODI will cache and not re-fetch the weather image, so inject a dummy time-stamp into the url to trick kodi because we want the new image
                nowtime = str(time.time())
                # Radar
                radarLoop = ADDON.getSetting('RadarLoop')

                # clean up previously fetched radar loop images
                imagepath = xbmcvfs.translatePath(
                    xbmcaddon.Addon().getAddonInfo('profile'))
                imagepath = imagepath+"cache/"
                if not os.path.isdir(imagepath):
                    os.makedirs(imagepath)
                for f in glob.glob(imagepath+"*.gif"):
                    os.remove(f)

                if (radarLoop == "true"):
                    # kodi will not loop gifs from a url, we have to actually
                    # download to a local file to get it to loop

                    # xbmc.log('Option To Loop Radar Selected',level=xbmc.LOGDEBUG)
                    xbmc.log('Option To Loop Radar Selected',
                             level=xbmc.LOGDEBUG)
                    url = f"https://radar.weather.gov/ridge/standard/{Station}_loop.gif"
                    radarfilename = f"radar_{Station}_{nowtime}.gif"
                    dest = imagepath+radarfilename
                    loop_image = get_url_image(
                        url, dest) if get_url_image(url, dest) else ''
                    set_property(f'Map.{1}.Area', loop_image)
                else:
                    url = f"https://radar.weather.gov/ridge/standard/{Station}_0.gif?{nowtime}"
                    set_property(f'Map.{1}.Area', url)
                    # clear_property('Map.%i.Area' % 1)
                    # set_property('Map.%i.Layer' % 1, url)

                clear_property(f'Map.{1}.Layer')
                set_property(f'Map.{1}.Heading', LANGUAGE(32334))

                # add satellite maps if we configured any
                for count in range(1, 5):
                    mcount = count+1
                    mapsector = ADDON.getSetting(f'Map{mcount}Sector')
                    maptype = ADDON.getSetting(f'Map{mcount}Type')
                    maplabel = ADDON.getSetting(f'Map{mcount}Label')

                    # xbmc.log('mapsector:maptype %s:%s' % (mapsector,maptype),level=xbmc.LOGERROR)

                    if (mapsector and maptype):

                        if ("RADAR_LOOP" == maptype):
                            # want looping radar gifs
                            if LOOPSECTORS.get(mapsector):
                                path = LOOPSECTORS.get(mapsector)['path']
                                url = f"https://radar.weather.gov/{path}"
                                imagename = f"radar_{mapsector}_{nowtime}.gif"
                                dest = imagepath+imagename
                                loop_image = get_url_image(url, dest)

                                set_property(f'Map.{mcount}.Area', loop_image)
                                set_property(
                                    f'Map.{mcount}.Heading', f"{maplabel}")
                                clear_property(f'Map.{mcount}.Layer')
                        else:

                            xname = MAPSECTORS.get(mapsector, {}).get('name')
                            xsat = MAPSECTORS.get(mapsector, {}).get('sat')
                            xloc = MAPSECTORS.get(mapsector)['loc']
                            xstatic = MAPSECTORS.get(mapsector)['static']
                            xloop = MAPSECTORS.get(mapsector)['loop']
                            xtype = MAPTYPES.get(maptype)['type']
                            xsubtype = MAPTYPES.get(maptype)['subtype']
                            ximagetype = MAPTYPES.get(maptype)['imagetype']
                            ximagename = ""
                            if ximagetype == "loop":
                                ximagename = "%s-%s-%s-%s" % (
                                    xsat, xloc, xsubtype, xloop)
                            else:
                                ximagename = xstatic

                            url = ""
                            if (xloc == 'CONUS'):
                                url = "https://cdn.star.nesdis.noaa.gov/%s/%s/CONUS/%s/%s?%s" % (
                                    xsat, xtype, xsubtype, ximagename, nowtime)
                            else:
                                url = "https://cdn.star.nesdis.noaa.gov/%s/%s/SECTOR/%s/%s/%s?%s" % (
                                    xsat, xtype, xloc.lower(), xsubtype, ximagename, nowtime)

#                            path = MAPSECTORS.get(mapsector)['path']
#                            if mapsector != 'glm-e' and mapsector != 'glm-w':
#                                path = path.replace("%s,%s",maptype)
#                                url="https://cdn.star.nesdis.noaa.gov/%s?%s" % (path,nowtime)

                            # xbmc.log('URL %s' % (url),level=xbmc.LOGERROR)

                            if ximagetype == "loop":
                                imagename = "%s-%s-%s-%s-%s" % (
                                    xsat, xloc, xsubtype, nowtime, xloop)
                                dest = imagepath+imagename
                                url = get_url_image(url, dest)

                            set_property(f'Map{mcount}.Area', url)
                            set_property(f'Map{mcount}.Heading', f"{maplabel}")
                            clear_property(f'Map{mcount}.Layer')
                    else:
                        clear_property(f'Map{mcount}.Area')
                        clear_property(f'Map{mcount}.Heading')
                        clear_property(f'Map{mcount}.Layer')
            else:
                log('no location provided')
                self.clear()
