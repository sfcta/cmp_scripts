import sys, os
import pandas as pd

nine_to_county = {1:'San Francisco',
                  2:'San Mateo',
                  3:'Santa Clara',
                  4:'Alameda',
                  5:'Contra Costa',
                  6:'Solano',
                  7:'Napa',
                  8:'Sonoma',
                  9:'Marin'}

purp_num_to_name18 = {1: 'Home',
                      2: 'Work',
                      3: 'Work-related',
                      4: 'School',
                      5: 'Escort',
                      6: 'Shop',
                      7: 'Meal', 
                      8: 'Social/rec',
                      9: 'Errand/appt',
                      10: 'Change mode',
                      11: 'Spent night other home',
                      12: 'Other/missing',
                      14: 'School-related'}

purp_num_to_name23 = {1: 'Home',
                      2: 'Work',
                      3: 'Work-related',
                      4: 'School',
                      5: 'School-related',
                      6: 'Escort',
                      7: 'Shop',
                      8: 'Meal', 
                      9: 'Social/rec',
                      10: 'Errand/appt',
                      11: 'Change mode',
                      12: 'Spent night other home',
                      13: 'Other/missing',
                     }
mode_num_to_name23 = {1:'Walk (or jog/wheelchair)',
                        2:'Standard bicycle (my household\'s)',
                        3:'Borrowed bicycle (e.g., a friend\'s)',
                        4:'Other rented bicycle',
                        5:'Other',
                        6:'Household vehicle 1',
                        7:'Household vehicle 2',
                        8:'Household vehicle 3',
                        9:'Household vehicle 4',
                        10:'Household vehicle 5',
                        11:'Household vehicle 6',
                        12:'Household vehicle 7',
                        13:'Household vehicle 8',
                        14:'Household vehicle 9',
                        15:'Household vehicle 10',
                        16:'Other vehicle in household',
                        17:'Rental car',
                        18:'Carshare service (e.g., Zipcar)',
                        21:'Vanpool',
                        22:'Other vehicle (not my household\'s)',
                        23:'Local (public) bus',
                        24:'School bus',
                        25:'Intercity bus (e.g., Greyhound, Megabus)',
                        26:'Other private shuttle/bus (e.g., a hotel\'s, an airport\'s)',
                        27:'Paratransit/Dial-A-Ride',
                        28:'Other bus',
                        30:'BART',
                        31:'Airplane/helicopter',
                        33:'Car from work',
                        34:'Friend/relative/colleague\'s car',
                        36:'Regular taxi (e.g., Yellow Cab)',
                        38:'University/college shuttle/bus',
                        41:'Intercity/Commuter rail (e.g., Altamount ACE, Amtrak, Caltrain)',
                        42:'Other rail',
                        43:'Skateboard or rollerblade',
                        44:'Golf cart',
                        45:'ATV',
                        47:'Other motorcycle in household',
                        49:'Uber, Lyft, or other smartphone-app ride service',
                        53:'MUNI Metro',
                        54:'Other motorcycle (not my household\'s)',
                        55:'Express bus or Transbay bus',
                        59:'Peer-to-peer car rental (e.g., Turo)',
                        60:'Other hired car service (e.g., black car, limo)',
                        61:'Rapid transit bus (BRT)',
                        62:'Employer-provided shuttle/bus',
                        63:'Medical transportation service',
                        67:'Local (private) bus (e.g., RapidShuttle, SuperShuttle)',
                        68:'Cable car or streetcar',
                        69:'Bike-share - standard bicycle',
                        70:'Bike-share - electric bicycle',
                        73:'Moped-share (e.g., Scoot)',
                        74:'Segway',
                        75:'Other',
                        76:'Carpool match (e.g., Waze Carpool)',
                        77:'Personal scooter or moped (not shared)',
                        78:'Public ferry or water taxi',
                        80:'Other boat (e.g., kayak)',
                        82:'Electric bicycle (my household\'s)',
                        83:'Scooter-share (e.g., Bird, Lime)',
                        100:'Household vehicle (or motorcycle)',
                        101:'Other vehicle (e.g., friend\'s car, rental, carshare, work car)',
                        102:'Bus, shuttle, or vanpool',
                        103:'Bicycle',
                        104:'Other',
                        105:'Rail (e.g., train, light rail, trolley, BART, MUNI Metro)',
                        106:'Uber/Lyft, taxi, or car service',
                        107:'Micromobility (e.g., scooter, moped, skateboard)',
                        995:'Missing Response',
                   }
county_order = ['San Francisco','San Mateo','Santa Clara','Alameda','Contra Costa','Solano','Napa','Sonoma','Marin']

class Survey(object):
    def __init__(self, household, person, day, trip, vehicle, location):
        self.hh = pd.read_csv(**household)
        self.person = pd.read_csv(**person)
        self.day = pd.read_csv(**day)
        self.trip = pd.read_csv(**trip)
        self.vehicle = pd.read_csv(**vehicle)
        self.location = pd.read_csv(**location)
        
        self.trip['purpose'] = self.trip['d_purpose_category']
        self.trip.loc[self.trip['d_purpose_category'].eq(1), 'purpose'] = self.trip['o_purpose_category']
        # household counts
        ## trips
        tc = self.trip.groupby('hh_id', as_index=False).size().rename(columns={'size':'trips'})
        tc = pd.merge(self.hh[['hh_id']], tc, on='hh_id', how='left')
        tc['trips'] = tc['trips'].fillna(0)
        
        ## days
        dc = self.day.groupby('hh_id', as_index=False).size().rename(columns={'size':'days'})
        dc = pd.merge(self.hh[['hh_id']], dc, on='hh_id', how='left')
        dc['days'] = dc['days'].fillna(0)
        
        ## persons
        pc = self.person.groupby('hh_id', as_index=False).size().rename(columns={'size':'persons'})
        pc = pd.merge(self.hh[['hh_id']], pc, on='hh_id', how='left')
        pc['persons'] = pc['persons'].fillna(0)
        
        self.hh_counts = pd.merge(pc, pd.merge(dc, tc, on='hh_id'), on='hh_id')
        
        # person counts
        ## trips
        tc = self.trip.groupby('person_id', as_index=False).size().rename(columns={'size':'trips'})
        tc = pd.merge(self.person[['person_id']], tc, on='person_id', how='left')
        tc['trips'] = tc['trips'].fillna(0)
        
        ## days
        dc = self.day.groupby('person_id', as_index=False).size().rename(columns={'size':'days'})
        dc = pd.merge(self.person[['person_id']], dc, on='person_id', how='left')
        dc['days'] = dc['days'].fillna(0)
        self.person_counts = pd.merge(tc, dc, on='person_id')
  
        # person day counts
        ## trips
        if 'day_id' not in self.trip.columns:
            self.trip['day_id'] = self.trip.apply(lambda x: '{}{:02d}'.format(x['person_id'], x['day_num']), axis=1)
        if 'day_id' not in self.day.columns:
            self.day['day_id'] = self.day.apply(lambda x: '{}{:02d}'.format(x['person_id'], x['day_num']), axis=1)
        tc = self.trip.groupby('day_id', as_index=False).size().rename(columns={'size':'trips'})
        tc = pd.merge(self.day[['day_id']], tc, on='day_id', how='left')
        tc['trips'] = tc['trips'].fillna(0)
        self.day_counts = tc.copy()
        
        # trip location counts
        tl = self.location.drop_duplicates().groupby('trip_id', as_index=False).size().rename(columns={'size':'locations'})
        tl = pd.merge(self.trip, tl, on='trip_id', how='left').fillna(0)
        self.trip_locations = tl.copy()