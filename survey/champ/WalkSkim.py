from champ.Skim import Skim
from tables import open_file
import numpy as np
from champ.Lookups import MAX_SF_ZONE

class WalkSkim(Skim):
    r"""
    Walk Skim class.
    
    For now, test with Y:\champ\networks\RTP2009_CHAMP4.3plus\2000\hwy\addPedAttributes\walkSkim.h5
    """
    
    #: Maps the table number to the name of the skim table
    TABLE_NUMBER_TO_NAME = { 
        1 :"DISTANCE",     # link sum.  (miles)
        2 :"INDIRECTNESS",   # distance divided by rock dove distance
        3 :"RISE",         # link sum   (feet)
        4 :"PER_RISE",     # Percent rise, or [rise / distance]
        5 :"ABS_RISE",     # link sum when rise>0 (feet)
        6 :"ABS_PER_RISE", # Percent rise [abs_rise / distance]
        # the following are weighted by link distance
        7:"AVGCAP",       # average road capacity (vph)
        8:"AVGLANEAM",    # average road lanes
        9:"AVGFFSPEED",   # average freeflow roadway speed
        # the following are TAZ-based.  Also weighted by link distance
        10:"AVGPOPDEN",    # average pop/acre
        11:"AVGEMPDEN",    # average employment/acre
        12:"AVGENTROPY",   # average entropy
        13:"AVGENTROPYNW", # average non-work entropy
        14:"AVGAREATYPE",  # average AREATYPE
    }
    TABLE_NAME_TO_NUMBER =  dict((v,k) for k,v in TABLE_NUMBER_TO_NAME.items())
    
    # TABLE_NAMES          =  list(TABLE_NUMBER_TO_NAME[i] for i in range(1,len(TABLE_NUMBER_TO_NAME)+1))
    
    ALL_VARS = list(TABLE_NUMBER_TO_NAME.values())
    
    def __init__(self, file_dir, file_name = "walkSkim.h5"):
        self.walk_skim_file = file_name
        Skim.__init__(self, file_dir, [self.walk_skim_file])        

    
    def getWalkSkimAttribute(self, orig_taz, dest_taz, attribute_name):
        """
        Returns the given walk skim attribute
        """    
        attribute_num = "%d" % WalkSkim.TABLE_NAME_TO_NUMBER[attribute_name]
        return self.skim_table_files[self.walk_skim_file].root._f_get_child(attribute_num)[orig_taz-1][dest_taz-1] 
    

    def getWalkSkimAttributes(self, orig_taz, dest_taz):
        """
        Returns all of the walk skim attributes in a dictionary (attribute name -> value)
        
        If you want to access ``DISTANCE``::
        
          walkSkimAttrs = walkSkim.getWalkSkimAttributes(otaz, dtaz)
          dist = walkSkimAttrs["DISTANCE"]
          
        """
        walkAttributes = {}
        for tableNum in list(WalkSkim.TABLE_NUMBER_TO_NAME.keys()):
            walkAttributes[WalkSkim.TABLE_NUMBER_TO_NAME[tableNum]] = \
                self.skim_table_files[self.walk_skim_file].root._f_get_child("%d" % tableNum)[orig_taz-1][dest_taz-1]
                    
        return walkAttributes
        
    def getSkimTable(self, variable):
        if variable.upper() not in WalkSkim.ALL_VARS: 
            print("Requested Variable %s not available" % (variable))
            exit(2)
        table    = np.zeros((MAX_SF_ZONE, MAX_SF_ZONE))
        tablenum = WalkSkim.TABLE_NAME_TO_NUMBER[variable.upper()]
        table[:,:] = self.skim_table_files[self.walk_skim_file].root._f_get_child("%d" % tablenum).read()[:MAX_SF_ZONE,:MAX_SF_ZONE]
        return table