# -*- coding: utf-8 -*-
"""Formatting-only pass for the pace-shootout block (AE-AJ) on New_Backtest_Clean_7.13.2026.
Values + legend already written. Applies integer format + pace-band shading to AE-AJ, extends the
row-1 group header across AA:AJ (robust unmerge of any existing row-1 merge first), styles headers,
sets column widths, and styles the relocated legend at AL:AM. Reads the live tab for row count."""
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds).spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
meta=sh.get(spreadsheetId=SEE).execute()
sheet=[x for x in meta['sheets'] if x['properties']['title']==TAB][0]; g=sheet['properties']['sheetId']
# row count from column E
E=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!E3:E5000").execute().get('values',[]); n=len(E)
LOW={'red':0.87,'green':0.93,'blue':0.99}; MID={'red':0.64,'green':0.80,'blue':0.93}; HIGH={'red':0.40,'green':0.61,'blue':0.84}
def rng_(c): return [{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}]
reqs=[]
# unmerge any existing row-1 merge at col>=26 (exact coords) so the big merge can be applied
for m in sheet.get('merges',[]):
    if m.get('startRowIndex')==0 and m.get('startColumnIndex',0)>=26:
        reqs.append({'unmergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':m['startColumnIndex'],'endColumnIndex':m['endColumnIndex']}}})
# integer format + pace bands on AE-AJ (cols 30-35)
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':30,'endColumnIndex':36},'cell':{'userEnteredFormat':{'numberFormat':{'type':'NUMBER','pattern':'0'}}},'fields':'userEnteredFormat.numberFormat'}})
for c in range(30,36):
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'40'}]},'format':{'backgroundColor':LOW}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_BETWEEN','values':[{'userEnteredValue':'40'},{'userEnteredValue':'64'}]},'format':{'backgroundColor':MID}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'64'}]},'format':{'backgroundColor':HIGH}}}}})
# group header AA1:AJ1 (26-36)
reqs.append({'mergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':36},'mergeType':'MERGE_ALL'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':36},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':30,'endColumnIndex':36},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)'}})
# widths: AE-AJ compact
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':30,'endIndex':36},'properties':{'pixelSize':92},'fields':'pixelSize'}})
# legend AL/AM styling (cols 37/38)
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':37,'endColumnIndex':39},'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat.textFormat'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':13,'startColumnIndex':38,'endColumnIndex':39},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':37,'endIndex':38},'properties':{'pixelSize':160},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':38,'endIndex':39},'properties':{'pixelSize':560},'fields':'pixelSize'}})
sh.batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
# verify
h=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!AA1:AM2").execute().get('values',[])
print('ROW1:',h[0][0] if h and h[0] else '')
print('ROW2:',h[1] if len(h)>1 else '')
print(f"formatted {n} rows. merges cleaned + AA1:AJ1 header, AE-AJ banded/integer, legend AL:AM styled.")
