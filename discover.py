import requests
import sys
import time

class FetchError(Exception):
    '''Custom error class when fetching does not meet our expectation.'''

def main():
    # Take the program arguments given to this script
    # Normal programs use 'argparse' but this keeps things simple
    item_value = sys.argv[1]
    item_type = sys.argv[2]
    output_filename = sys.argv[3]  # this should be something like myfile.txt.gz
    start_num, end_num = item_value.split('-')

    if item_type == "profiles":
        profiles = []
        for profileid in range(int(start_num), int(end_num) + 1):
            status_code = str(check_200('http://www.livejournal.com/profile?userid='+str(profileid)))
            print('Received status code ' + status_code + ' for profile ' + str(profileid) + '.')
            sys.stdout.flush()
            profiles.append(str(profileid) + ',' + status_code)
            time.sleep(5)

        with open(output_filename, 'w') as file:
            file.write('\n'.join(profiles))

def check_200(url):
    tries = 0
    status_code = 0
    MAX_TRIES = 10
    while tries <= MAX_TRIES:
        try:
            response = requests.get(url, timeout=10)
        except requests.exceptions.RequestException:
            print('Connection error. Sleeping for 10 seconds...')
            tries += 1
            time.sleep(10)
            continue
        status_code = response.status_code
        if response.status_code == 403 and not '<title>Suspended Journal</title>' in response.text:
            print('You\'re banned from LiveJournal. Sleeping for 1 hour, then ABORTING.')
            time.sleep(3600)
            raise Exception('Banned from LiveJournal. ABORTING.')
        elif response.status_code not in (200, 404, 410, 403, 500):
            tries += 1
        else:
            return status_code
    if tries <= MAX_TRIES:
        return status_code
    else:
        raise Exception('Subsequent failed attempts. ABORTING.')

if __name__ == '__main__':
    main()

