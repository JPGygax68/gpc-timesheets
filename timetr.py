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
import webbrowser

from lib.query_yes_no import query_yes_no


BASE_URL = 'https://app.trackingtime.co/api/v4/'

# If modifying these scopes, delete your previously saved credentials
# at ~/.credentials/sheets.googleapis.com-python-quickstart.json
SCOPES = BASE_URL # 'https://www.googleapis.com/auth/spreadsheets.readonly'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'GPC Timesheets'

ACCOUNT_ID = 243645 # TODO: obtain via authentication data

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

# Configuration ---------------------------------------------------------------

def get_update_config():
    """Read, update and write config file (username and password for now)"""

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
        
    return config


# REST transactions -----------------------------------------------------------

def get_events(customer_id, user_id):
    auth = config['authentication']
    response = requests.get(BASE_URL+str(ACCOUNT_ID)+'/events', 
        auth=(auth['username'], auth['password']), 
        params = {'filter': 'USER', 'id': user_id, 'from': '1970-01-01', 'to': '2999-12-31'}
            # TODO: the above filter should try to avoid re-scanning too far back in time
    )
    response.raise_for_status()
    events = json.loads(response.text)['data']
    for event in events:
        event = namedtuple('Event', event.keys())(**event)
        if event.user_id == user_id:
            if event.customer_id == customer_id:
                if not event.is_billed:
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
    
def set_event_billed(id):
    auth = config['authentication']
    response = requests.get(BASE_URL+str(ACCOUNT_ID)+'/events/update/'+str(id)+'?is_billed=true', 
        auth=(auth['username'], auth['password']))
    response.raise_for_status()

# "Billing sheet" implementation ----------------------------------------------

def generate_billing_sheet(args):

    MAX_SPANS_PER_TASK = 5
    NB_OF_COLUMNS = 6 + MAX_SPANS_PER_TASK
        
    def timesheet_rows(customer_id, user):

        def complete_spans(list_ = []):
            while len(list_) < MAX_SPANS_PER_TASK:
                list_.append(td(class_='span'))
        
        last_date = date(1, 1, 1)
        last_project = None
        last_task_id = -1
        last_event = None
        day_dur = timedelta()
        total_dur = timedelta()
        total_amount = 0.0
        span_list = []

        def generate_task_row():
            nonlocal last_event, span_list, day_dur, total_amount
            if len(span_list) > 0: # day_dur > timedelta():
                #print("generating task row, span_list:", len(span_list))
                complete_spans(span_list)
                rate = 0 if last_event.hourly_rate is None else last_event.hourly_rate
                amount = (day_dur.seconds / 3600) * rate
                total_amount += amount
                yield tr( td(), td(), 
                    td(class_='task')(last_event.task if not last_event.task is None else '(allgemein)'), 
                    td(class_='duration')('{:02}:{:02}'.format(day_dur.seconds // 3600, (day_dur.seconds // 60) % 60)),
                    td(class_='rate')(int(rate)),
                    td(class_='amount')('{:.2f}'.format(amount)),
                    *span_list )
            day_dur = timedelta()
            span_list = []
            
        for e in get_events(customer_id, user.id):
            tss = datetime.strptime(e.start, '%Y-%m-%d %H:%M:%S')
            tse = datetime.strptime(e.end  , '%Y-%m-%d %H:%M:%S')
            dur = tse - tss
            #print("project:", last_project, "task id:", last_task_id, "durations:", len(span_list))
            #print("start: ", tss)
            if tss.date() != last_date:
                #print("new date")
                for _ in generate_task_row(): yield _
                yield tr(
                    th(class_='date-header', colspan=NB_OF_COLUMNS)(format_date(tss.date(), format='EEEE, d.M.yyyy', locale='de_CH')) 
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
            day_dur += dur
            total_dur += dur
        for _ in generate_task_row(): yield _
        # Total row
        #print('total_dur:', total_dur)
        tot_hours = total_dur.days * 24 + total_dur.seconds // 3600
        rem_minutes = total_dur.seconds // 60 % 60
        yield tr(class_='total')(
            td(colspan=3)('TOTAL'), 
            td(class_='duration')('{:d}:{:02d}'.format(tot_hours, rem_minutes)),
            td(), 
            td(class_='amount')('{:.2f}'.format(total_amount)),
            td(colspan=MAX_SPANS_PER_TASK)()
        )

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
    css_file = os.path.join(os.path.dirname(__file__), 'data', 'style.css')
    with open(css_file) as f:
        css_text = f.read()
    
    code = html(
        head(
            meta(charset='utf-8'),
            title('Gearbeitete Zeit'), # TODO: more information
            #link(rel='stylesheet', href='style.css'),
            style(type='text/css')(Safe(css_text))
        ),
        body(
            table(
                thead( 
                    tr(class_='header')(
                        th(colspan=3)('Datum, Projekt, Aufgabe'), th('Dauer'), th('Ansatz'), th('Total'),
                        *[th(class_='span')('Per.\u00A0'+str(i+1)) for i in range(MAX_SPANS_PER_TASK)]
                    )
                ),
                tbody( timesheet_rows(customer.id, user) )
            )
        )
    )

    out_filename = 'output/timesheet.html'
    s = str(code)
    with open(out_filename, 'w', encoding='utf-8') as f:
        f.write(s)
        
    # Open file in web browser
    webbrowser.open("file://"+os.path.abspath(out_filename), new = 2)
    
    # Mark as billed ?
    if args.mark_billed:
        if query_yes_no('Do you really want to mark all events as billed ?') == 'yes':
            n = 0
            for e in get_events(customer.id, user.id):
                set_event_billed(e.id)
                n += 1
            print("{:d} events marked as billed".format(n))
    
# Main routine ----------------------------------------------------------------

parser = argparse.ArgumentParser(description='GPC time tracking commands')
subparsers = parser.add_subparsers()

#p_customers = subparsers.add_parser('customers')

p_billing = subparsers.add_parser('billing', description='Generate timesheet for specific customer from TrackingTime data')
p_billing.add_argument('customer_name_or_id', help='Customer name or ID')
p_billing.add_argument('--mark-billed', action='store_true', help='Mark events as billed once timesheet has been generated')
p_billing.set_defaults(func=generate_billing_sheet)

args = parser.parse_args()
#print('command:', args.command)

config = get_update_config()

# Execute specified subcommand

if hasattr(args, 'func'):
    args.func(args)
else:
    print('No command given, doing nothing')
