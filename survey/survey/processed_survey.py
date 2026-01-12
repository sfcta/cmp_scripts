import sys, os
import numpy as np
import pandas as pd

from champ.HwySkimUtil import SkimUtil2
from champ.TransitTourSkim import TransitTourSkim
from champ.WalkSkim import WalkSkim

PURP_DICT = {1:'Work',    #work -> work
             2:'School',    #school -> school
             3:'Escort',    #escort -> escort
             4:'Pers. Bus',    #work-related -> work
             5:'Shop',    #shop -> shop
             6:'Meal',    #meal -> meal
             7:'Soc/Rec',    #socrec -> socrec
             8:'Rec',
             9:'Med',
             10:'Change mode',  #change mode -> change mode
             11:'Other',  #night non-home -> other
             98:'Other',
             99:'Workbased'
            }
MODE_DICT = {0:'Other',
             1:'Walk',
             2:'Bike',
             3:'Drive Alone',
             4:'Shared Ride 2',
             5:'Shared Ride 3+',
             6:'Walk-Transit',
             7:'Drive-Transit',
             #8:'School Bus',
             8:'Walk-Transit',
             9:'TNC'
             }

class SurveyTable(object):
    def __init__(self, dir, file=None, **kwargs):
        self.data = None
        self.weight = None
        self.records = 0
        self.nonzero_records = 0
        self.sum_of_weights = 0
        
        if kwargs != None:
            if 'weight' in kwargs:
                self.weight = kwargs.pop('weight')
        else:
            kwargs = {}
            
        if file != None:
            kwargs['filepath_or_buffer'] = os.path.join(dir, file)
            self.data = pd.read_csv(**kwargs)
            
            self.records = len(self.data)
            self.nonzero_records = len(self.data.loc[self.data[self.weight].ne(0)])
            self.sum_of_weights = self.data[self.weight].sum()
            
    def update_statistics(self):
        if isinstance(self.data, pd.DataFrame):
            self.records = len(self.data)
            self.nonzero_records = len(self.data.loc[self.data[self.weight].ne(0)])
            self.sum_of_weights = self.data[self.weight].sum()
        else:
            self.records = 0
            self.nonzero_records = 0
            self.sum_of_weights = 0

class ProcessedSurvey(object):
    def __init__(self, dir=None, hh=None, person=None, day=None, tour=None, trip=None, raw_dir=None, raw_hh=None, raw_person=None, raw_day=None, raw_trip=None, **kwargs):
        '''
        '''        
        if hh == None:
            hh = {}
        if person == None:
            person = {}
        if day == None:
            day = {}
        if trip == None:
            trip = {}
        if tour == None:
            tour = {}
        
        self.hh = SurveyTable(dir, **hh)
        self.person = SurveyTable(dir, **person)
        self.day = SurveyTable(dir, **day)
        self.tour = SurveyTable(dir, **tour) 
        self.trip = SurveyTable(dir, **trip)
        
        self.link_drive_transit_trips()
        
        if raw_hh == None:
            raw_hh = {}
        if raw_person == None:
            raw_person = {}
        if raw_day == None:
            raw_day = {}
        if raw_trip == None:
            raw_trip = {}

        self._raw_hh = SurveyTable(raw_dir, **raw_hh)
        self._raw_person = SurveyTable(raw_dir, **raw_person)
        self._raw_day = SurveyTable(raw_dir, **raw_day)
        self._raw_trip = SurveyTable(raw_dir, **raw_trip)
        
        self._rename_raw()
        self._attach_raw()
        #if isinstance(self.trip, SurveyTable):
        #    self.day_trips = self.trip.groupby(['hhno','pno','day'], as_index=False).size().rename(columns={'size':'trips'})
        
        #if isinstance(self.tour, SurveyTable):
        #    self.day_trips = self.tour.groupby(['hhno','pno','day'], as_index=False).size().rename(columns={'size':'tours'})
        
    def _update_statistics(self):
        self.hh.update_statistics()
        self.person.update_statistics()
        self.day.update_statistics()
        self.trip.update_statistics()
        self.tour.update_statistics()
        
    def summarize(self):
        self._update_statistics()
        df = pd.Series(index=['hh_records',
                             'person_records',
                             'day_records',
                             'trip_records',
                             'tour_records',
                             'hh_records_nonzero',
                             'person_records_nonzero',
                             'day_records_nonzero',
                             'trip_records_nonzero',
                             'tour_records_nonzero',
                             'hh_weight',
                             'person_weight',
                             'day_weight',
                             'trip_weight',
                             'tour_weight'],
                       data=[self.hh.records,
                             self.person.records,
                             self.day.records,
                             self.trip.records,
                             self.tour.records,
                             self.hh.nonzero_records,
                             self.person.nonzero_records,
                             self.day.nonzero_records,
                             self.trip.nonzero_records,
                             self.tour.nonzero_records,
                             self.hh.sum_of_weights,
                             self.person.sum_of_weights,
                             self.day.sum_of_weights,
                             self.trip.sum_of_weights,
                             self.tour.sum_of_weights,
                             ])
        return df
        
    def link_drive_transit_trips(self):
        if 'otaz_drive' in self.trip.data.columns:
            return
        
        df = self.trip.data.copy()
        dtrn_df = df.loc[df['dpurp']==10,]
        dtrn_df.loc[:,'tseg'] += 1
        dtrn_df = dtrn_df[['hhno','pno','day','tour','half','tseg','otaz','opurp']]
        dtrn_df  = dtrn_df.rename(columns={'otaz':'otaz_drive','opurp':'opurp_drive'})
        df = df.loc[df['dpurp']!=10,]
        df = df.merge(dtrn_df, on=['hhno','pno','day','tour','half','tseg'], how='left')
        df.loc[df['opurp']==10, 'otaz'] = df.loc[df['opurp']==10, 'otaz_drive']
        df.loc[df['opurp']==10, 'mode'] = 7
        df.loc[df['opurp']==10, 'opurp'] = df.loc[df['opurp']==10, 'opurp_drive']
        self.trip.data = df
        self.trip.update_statistics()
    
    def attach_skims(self, skim_dir, walk_speed=3):
        '''
        Attach distance skims for trips and point-of-interest(poi)-to-poi skims from AM drive
        
        Attach drive time skims for poi-to-poi from AM drive
        Attach transit time skims for poi-to-poi from AM transit tour
        '''
        
        # driving skims
        hwySkim = SkimUtil2(skim_dir)
            
        # transit skims
        trnSkim = TransitTourSkim(skim_dir)
        
        # walk skims
        walkskim = WalkSkim(skim_dir).getSkimTable('DISTANCE') * (60.0 / walk_speed)
        
        if self.trip.records > 0:
            trip = self.trip.data.copy()
            for i in range(len(trip)):
                otaz = int(trip['otaz'][i])
                dtaz = int(trip['dtaz'][i])
                if otaz>0 and dtaz>0:
                    skims = hwySkim.getDASkims(otaz,dtaz)
                    trip.loc[i,'travdist'] = skims[1]
            #trip = trip[trip['travdist']>0]
            self.trip.data = trip.fillna(-1)
            
        if self.person.records > 0:
            if not 'hhtaz' in self.person.data.columns:
                self.person.data = pd.merge(self.person.data,
                                            self.hh.data[['hhno','hhtaz','hhincome']])
            
            # point-of-interest dist / times
            poi = self.person.data.copy()
            for i in range(len(poi)):
                otaz = int(poi['hhtaz'][i])
                dtaz = int(poi['pwtaz'][i])
                if otaz>0 and dtaz>0:
                    hwy = hwySkim.getDASkims(otaz,dtaz)
                    poi.loc[i,'hw_dist'] = hwy[1]
                    poi.loc[i,'hw_drive_time'] = hwy[0]
                    
                    trn = trnSkim.getTourAttributes(otaz,dtaz)[0]
                    w = walkskim[otaz-1,dtaz-1]
                    if trn == 0:
                        trn = w
                    elif w > 0:
                        trn = min(trn, w)
                    
                    poi.loc[i,'hw_transit_time'] = trn
            
                otaz = int(poi['hhtaz'][i])
                dtaz = int(poi['pstaz'][i])
                if otaz>0 and dtaz>0:
                    hwy = hwySkim.getDASkims(otaz,dtaz)
                    poi.loc[i,'hs_dist'] = hwy[1]
                    poi.loc[i,'hs_drive_time'] = hwy[0]
                    
                    trn = trnSkim.getTourAttributes(otaz,dtaz)[0]
                    w = walkskim[otaz-1,dtaz-1]
                    if trn == 0:
                        trn = w
                    elif w > 0:
                        trn = min(trn, w)
                        
                    poi.loc[i,'hs_transit_time'] = trn
                    
            self.person.data = poi.fillna(-1) 
        
        if self.tour.records > 0:
            if not 'hhtaz' in self.tour.data.columns:
                self.tour.data = pd.merge(self.tour.data,
                                            self.hh.data[['hhno','hhtaz','hhincome']])
            
            # point-of-interest dist / times
            poi = self.tour.data.copy()
            for i in range(len(poi)):
                otaz = int(poi['totaz'][i])
                dtaz = int(poi['tdtaz'][i])
                if otaz>0 and dtaz>0:
                    hwy = hwySkim.getDASkims(otaz,dtaz)
                    poi.loc[i,'pd_dist'] = hwy[1]
                    poi.loc[i,'pd_drive_time'] = hwy[0]
                    
                    trn = trnSkim.getTourAttributes(otaz,dtaz)[0]
                    w = walkskim[otaz-1,dtaz-1]
                    if trn == 0:
                        trn = w
                    elif w > 0:
                        trn = min(trn, w)
                        
                    poi.loc[i,'pd_transit_time'] = trn
                    
            self.tour.data = poi.fillna(-1) 
        
        self._update_statistics()
    
    def _attach_raw(self):
        if self._raw_day.records > 0:
            _columns = ['hhno',
                       'pno',
                       'day',
                       'telecommute_time',
                       'no_travel_1',  # did make trips
                       'no_travel_2',  # day off
                       'no_travel_3',  # worked from home for pay
                       'no_travel_4',  # hung out around home
                       'no_travel_5',  # scheduled school closure
                       'no_travel_6',  # no available transportation
                       'no_travel_7',  # sick
                       'no_travel_8',  # waited for visitor / delivery / service
                       'no_travel_9',  # kids did online / remote / home school
                       'no_travel_11', # weather
                       'no_travel_12', # possibly made trips
                       'no_travel_99', # other reason
                       
                       'telework_time',
                       'no_travel_weather',
                       'no_travel_no_work',
                       'no_travel_telework',
                       'no_travel_house_work',
                       'no_travel_kids_break',
                       'no_travel_kids_homeschooled',
                       'no_travel_no_transport',
                       'no_travel_sick',
                       'no_travel_delivery',
                       'no_travel_other',
                       'no_trips_from_rmove',

                       'num_reasons_no_travel',
                      ]
            columns = []

            if 'telework_time' in self._raw_day.data.columns:
                self._raw_day.data.rename(columns={'telework_time':'telecommute_time'}, inplace=True)
            if 'no_travel_telework' in self._raw_day.data.columns:
                self._raw_day.data.rename(columns={'no_travel_telework':'no_travel_3'}, inplace=True)
            if not 'num_reasons_no_travel' in self._raw_day.data.columns:
                self._raw_day.data['num_reasons_no_travel'] = 0
                for c in columns:
                    if 'no_travel' in c:
                        self._raw_day.data['num_reasons_no_travel'] += self._raw_day.data[c]
                        
            for c in _columns:
                # check if the raw columns are already joined
                if c not in ['hhno','pno','day'] and c in self.day.data.columns:
                    return
                    
                if c in self._raw_day.data.columns:
                    columns.append(c)            
                
            self.day.data = pd.merge(self.day.data,
                                     self._raw_day.data[columns],
                                     how='left')
            try:
                self.day.data['wfh'] = ((self.day.data['telecommute_time'].ge(180) | 
                                        self.day.data['no_travel_3'].eq(1)) &
                                        self.day.data['wktours'].eq(0)) * 1
            except:
                print('could not calculate wfh')
                
        if self._raw_trip.records > 0:
            columns = ['hhno',
                       'pno',
                       'tsvid',
                       'mode_type']
            self.trip.data = pd.merge(self.trip.data,
                                      self._raw_trip.data[columns],
                                      how='left')
    
    def _rename_raw(self):
        if self._raw_hh.records > 0:
            (self._raw_hh
                 .data.rename(columns={'hh_id':'hhno'},
                              inplace=True))
        if self._raw_person.records > 0:
            (self._raw_person
             .data.rename(columns={'hh_id':'hhno',
                                   'person_num':'pno'},
                          inplace=True))
        if self._raw_day.records > 0:
            rename = {'hh_id':'hhno',
                      'person_num':'pno',
                     }
            if 'travel_dow' in self._raw_day.data.columns:
                rename['travel_dow'] = 'day'
            elif 'travel_date_dow' in self._raw_day.data.columns:
                rename['travel_date_dow'] = 'day'
            (self._raw_day
             .data.rename(columns=rename,
                          inplace=True))
        if self._raw_trip.records > 0:
            rename = {'hh_id':'hhno',
                      'person_num':'pno',
                     }
            if 'travel_dow' in self._raw_trip.data.columns:
                rename['travel_dow'] = 'day'
            elif 'travel_date_dow' in self._raw_trip.data.columns:
                rename['travel_date_dow'] = 'day'
                
            if 'trip_num' in self._raw_trip.data.columns:
                rename['trip_num'] = 'tsvid'
            elif 'linked_trip_id' in self._raw_trip.data.columns:
                rename['linked_trip_id'] = 'tsvid'
            (self._raw_trip
             .data.rename(columns=rename,
                          inplace=True))