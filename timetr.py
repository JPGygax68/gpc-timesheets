#!python

import os
import sys
import argparse
import getpass
from pyreadline import Readline
from configobj import ConfigObj
import requests
import json
from collections import namedtuple
from pyhtml import *
from datetime import datetime, date, time, timedelta
from babel.dates import format_date, format_time


BASE_URL = 'https://app.trackingtime.co/api/v4/'

# If modifying these scopes, delete your previously saved credentials
# at ~/.credentials/sheets.googleapis.com-python-quickstart.json
SCOPES = BASE_URL # 'https://www.googleapis.com/auth/spreadsheets.readonly'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'GPC Timesheets'

ACCOUNT_ID = 243645

MAX_SPANS_PER_TASK = 5
    
NB_OF_COLUMNS = 1 + 1 + 1 + 1 + MAX_SPANS_PER_TASK
    
config = None

# Generic routines ------------------------------------------------------------

def input_default(prompt, default):
    #readline = Readline()
    return input("%s [%s] " % (prompt, default)) or default
    
def get_user_from_account(account_id):
    auth = config['authentication']
    response = requests.get(BASE_URL+'users', auth=(auth['username'], auth['password']))
    response.raise_for_status()
    users = json.loads(response.text)['data']
    for user in users:
        user = namedtuple('User', user.keys())(**user)
        if user.account_id == ACCOUNT_ID:
            return user
    raise Exception("Could not find user from account ID")


# REST transactions -----------------------------------------------------------

def get_events(customer_id, user_id):
    auth = config['authentication']
    response = requests.get(BASE_URL+str(ACCOUNT_ID)+'/events', 
        auth=(auth['username'], auth['password']), 
        params = {'filter': 'USER', 'id': user_id, 'from': '2017-01-01', 'to': '2017-09-30'})
    response.raise_for_status()
    events = json.loads(response.text)['data']
    for event in events:
        event = namedtuple('Event', event.keys())(**event)
        if event.user_id == user_id:
            if event.customer_id == customer_id:
                yield event
    
def get_customer_by_name(name):
    auth = config['authentication']
    response = requests.get(BASE_URL+str(ACCOUNT_ID)+'/customers', 
        auth=(auth['username'], auth['password']))
    response.raise_for_status()
    customers = json.loads(response.text)['data']
    for cust in customers:
        cust = namedtuple('Customer', cust.keys())(**cust)
        if cust.name == name:
            return cust
    raise Exception('No customer found under the name "%s"' % name)
    

# "Billing" implementation ----------------------------------------------------

def generate_billing_sheet(args):

    def timesheet_rows(customer_id, user):

        def complete_spans(list_ = []):
            while len(list_) < MAX_SPANS_PER_TASK:
                list_.append(td(class_='span'))
        
        last_date = date(1, 1, 1)
        last_project = None
        last_task_id = -1
        last_event = None
        total_dur = timedelta()
        span_list = []

        def generate_task_row():
            nonlocal last_event, span_list, total_dur
            if len(span_list) > 0: # total_dur > timedelta():
                #print("generating task row, span_list:", len(span_list))
                complete_spans(span_list)
                yield tr( td(), td(), td(class_='task')(last_event.task if not last_event.task is None else '(allgemein)'), 
                    td(class_='duration')('{:02}:{:02}'.format(total_dur.seconds // 3600, (total_dur.seconds // 60) % 60)), 
                    *span_list )
            total_dur = timedelta()
            span_list = []
            
        for e in get_events(customer_id, user.id):
            tss = datetime.strptime(e.start, '%Y-%m-%d %H:%M:%S')
            tse = datetime.strptime(e.end  , '%Y-%m-%d %H:%M:%S')
            dur = tse - tss
            #print("project:", last_project, "task id:", last_task_id, "durations:", len(span_list))
            if tss.date() != last_date:
                #print("new date")
                for _ in generate_task_row(): yield _
                yield tr(
                    th(class_='date-header', colspan=NB_OF_COLUMNS)(format_date(tss.date(), format='long', locale='de_CH')) 
                        # TODO: obtain locale from somewhere! (and make it overridable ?)
                )
                last_date = tss.date()
                last_project = None;
            if e.project != last_project:
                #print("new project")
                for _ in generate_task_row(): yield _
                yield tr( th(), th(class_='project-header', colspan=11)(e.project) )
                last_project = e.project
                last_task_id = -1
            if e.task_id != last_task_id:
                #print("new task")
                for _ in generate_task_row(): yield _
                last_task_id = e.task_id
            span_list.append(td(class_='span')(format_time(tss, 'HH:mm') + '\N{NON-BREAKING HYPHEN}' + format_time(tse, 'HH:mm')))
            # For next iteration
            last_event = e
            total_dur += dur
        for _ in generate_task_row(): yield _

    #print("generate_billing_sheet")
    
    # Get user record
    user = get_user_from_account(ACCOUNT_ID)
    #print('User ID:', user.id)
    
    # Look up customer record
    try:
        id = int(args.customer_name_or_id)
    except ValueError:
        id = 0
    if id != 0:
        customer = get_customer_by_id(id)
        print('(Customer name: %s)' % customer.name)
    else:
        customer = get_customer_by_name(args.customer_name_or_id)
        print('(Customer ID: %s)' % customer.id)
        
    # Generate HTML file (TODO: open in "print" mode)
    
    code = html(
        head(
            title('Gearbeitete Zeit'), # TODO: more information
            link(rel='stylesheet', href='style.css'),
        ),
        body(
            table(
                thead( 
                    tr(class_='header')(
                        th(colspan=3)('Datum, Projekt, Aufgabe'), th('Dauer'), 
                        *[th(class_='span')('Per.\u00A0'+str(i+1)) for i in range(MAX_SPANS_PER_TASK)]
                    )
                ),
                tbody( timesheet_rows(customer.id, user) )
            )
        )
    )

    s = str(code)
    with open('output/timesheet.html', 'w', encoding='utf-8') as f:
        f.write(s)
    
# Main routine ----------------------------------------------------------------

parser = argparse.ArgumentParser(description='GPC time tracking commands')
#parser.add_argument('command', nargs='?', const='customers')
subparsers = parser.add_subparsers()

#p_customers = subparsers.add_parser('customers')

p_billing = subparsers.add_parser('billing', description='Generate timesheet for specific customer from TrackingTime data')
p_billing.add_argument('customer_name_or_id', help='Customer name or ID')
p_billing.set_defaults(func=generate_billing_sheet)

args = parser.parse_args()
#print('command:', args.command)

# Read, update and write config file (username and password for now)

home_dir = os.path.expanduser('~')
config_dir = os.path.join(home_dir, '.gpc-timesheets')
config_file = os.path.join(config_dir, 'parameters.cfg')
if os.path.exists(config_file):
    print("Config file found, reading...")
    config = ConfigObj(config_file)
else:
    config = ConfigObj()
    config.filename = config_file
    config['authentication'] = { 'username': getpass.getuser() }
auth = config['authentication']

if auth['username'] is None:
    auth['username'] = input_default('Username: ', config['authentication']['username'])
    pwd = getpass.getpass('Password: ')
    if pwd: # keep previous password if entered empty
        auth['password'] = pwd  # TODO: encrypt password ?

    if not os.path.exists(config_dir): os.makedirs(config_dir)
    config.write()
    print("Configuration written to \"%s\"" % config.filename)

# Execute specified subcommand

args.func(args)

if False:
    # Branch into subcommand

    if args.command is None or args.command == 'customers':
        print("customers")

    elif args.command == 'billing':
        print("customer_name_or_id:", args.customer_name_or_id)
        #print("Username:", auth['username'])
        #print("Password:", auth['password'])

    sys.exit(0)





#users = json.loads(response.text)['data']
#print(json.dumps(users, indent=4))

if False:
    for user in users:
        #print(user['name'] + ' ' + user['surname'])    
        u2 = namedtuple('User', user.keys())(**user)
        print(u2)
        #print(u2)
        print(u2.name + ' ' + u2.surname)


