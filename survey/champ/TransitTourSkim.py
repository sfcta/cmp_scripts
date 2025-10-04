from champ.Skim import Skim
from tables import open_file

class TransitTourSkim(Skim):
    """
    Transit Tour Skim class.
    """
    
    #: Matching of matrix in h5 file and attribute name
    TABLE_NUMBER_TO_NAME = {1:"LIVT", 2:"RIVT", 3:"MIVT", 4:"PIVT", 5:"FIVT", 6:"BIVT", 
                            7:"ACC_TIME", 8:"EGR_TIME", 9:"ACC_DIST", 10:"EGR_DIST",
                            11:"IWAIT", 12:"XWAIT", 
                            13:"TrDIST", 14:"DrDIST", 
                            15:"FUNTIME", 16:"XWKTIME", 17:"NUM_LINKS", 18:"TOT_FARE",
                            19:"ACCNODE", 20:"EGRNODE"}
    
    #: All variables returned
    ALL_VARS = list(TABLE_NUMBER_TO_NAME.values())
    ALL_VARS.append("TOT_TIME")
    
    #: Skims related to time (for converting hundredths of mins to mins)
    TIME_SKIMS = ["LIVT", "RIVT", "MIVT", "PIVT", "FIVT", "BIVT",
                  "ACC_TIME", "EGR_TIME", "IWAIT", "XWAIT", "FUNTIME", "XWKTIME"]
    #: Skims related to distances (for converting hundredths of miles to miles)
    DIST_SKIMS = ["TrDIST", "DrDIST", "ACC_DIST", "EGR_DIST"]
    #: Skims related to cost
    FARE_SKIMS = ["TOT_FARE"]

    #: Tour Skim types, e.g. WTW, etc
    TOUR_SKIM_TYPES = ["WTW"] # ["WTW", "ATW", "WTA"]

    def __init__(self, file_dir, timeperiod="AM"):
        """
        Opens the given skim
        """
        self.timeperiod = timeperiod
        self.trn_skim_files = list("TRN%s%s.h5" % (tourtype, timeperiod)
                                   for tourtype in TransitTourSkim.TOUR_SKIM_TYPES)
        
        Skim.__init__(self, file_dir, self.trn_skim_files)
          
    def getTourAttributes(self, otaz, dtaz, tour_type="WTW"):
        """
        Returns a tuple of (time, distance, fare)
        
        `tour_type` is one of :py:attr:`TransitTourSkim.TOUR_SKIM_TYPES`

        Units are minutes, miles and 1989 cents.

        Currently this only returns outbound OR return (not the sum) depending on how called.

        A value for `TOT_TIME` is also included for convenience.
        
        """
        skim_file = "TRN%s%s.h5" % (tour_type, self.timeperiod)
        
        transitAttributes = {}
        tot_time = 0
        tot_dist = 0
        
        for tablenum,tablename in TransitTourSkim.TABLE_NUMBER_TO_NAME.items():
            # convert hundredths of minutes to minutes
            if tablename in TransitTourSkim.TIME_SKIMS:
                transitAttributes[tablename] = 0.01 * self.skim_table_files[skim_file].root._f_get_child("%d" % tablenum)[otaz-1][dtaz-1]
                tot_time += transitAttributes[tablename]
                
            # convert hundredths of miles to miles
            elif tablename in TransitTourSkim.DIST_SKIMS:
                transitAttributes[tablename] = 0.01 * self.skim_table_files[skim_file].root._f_get_child("%d" % tablenum)[otaz-1][dtaz-1]
                tot_dist += transitAttributes[tablename]
            # FAREs are in the correct units already
            else:
                transitAttributes[tablename] = self.skim_table_files[skim_file].root._f_get_child("%d" % tablenum)[otaz-1][dtaz-1]
                    
        transitAttributes["TOT_TIME"] = tot_time
        
        return (tot_time, tot_dist, transitAttributes['TOT_FARE'])
        