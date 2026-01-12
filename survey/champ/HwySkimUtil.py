'''
Created on Jan 25, 2010

@author: Lisa Zorn

Generic trip record class, plus some extra functions that will likely come up.

Modified in 2014 by Bhargava Sana to just isolate a skim query functionality.
'''

from tables import open_file
import os

# Functionally constants
TIMEPERIODS     = { 1:"EA", 2:"AM", 3:"MD", 4:"PM", 5:"EV" }

class SkimUtil2:
    """
    Helper class to read Skim files and lookup time/cost/distance for given O-D pairs.
    This class is written for low-memory, not for speed.  So it'll take forever to go
    through a trip file and do the skim lookups but you won't be hitting memory limits.
    """
    
    def __init__(self, skimdir, timeperiods=[2], skimprefix=""):
            
        self.skimdir         = skimdir
        self.hwyskims        = { 1:{}, 2:{}, 3:{}, 4:{}, 5:{} }
        for tkey in timeperiods:
            self.hwyskims[tkey] = open_file(os.path.join(skimdir,skimprefix+"HWYALL" + TIMEPERIODS[tkey] + ".h5"), mode="r")
        self.termtime        = open_file(os.path.join(skimdir,"OPTERM.h5"), mode="r")

        print("SkimUtil2 initialized for " + skimdir)

    def getDASkims(self, otaz, dtaz, timeperiod=2):
        """ Returns distance, time, out-of-pocket cost (fares, bridge & value tolls)
            Units: miles, minutes, 1989 dollars.
        """
            
        (t,d,f) = (0,0,0)
        termtime                = 0

        # this is ok because of the PNR zones
        if (otaz >= self.termtime.get_node('/', '1').shape[0] or
            dtaz >= self.termtime.get_node('/', '1').shape[0]):
            termtime = 0
        else:
            termtime = self.termtime.get_node('/', '1')[otaz-1][dtaz-1]

        t = self.hwyskims[timeperiod].get_node('/', '1')[otaz-1,dtaz-1] + termtime
        d = self.hwyskims[timeperiod].get_node('/', '2')[otaz-1,dtaz-1]
        f = self.hwyskims[timeperiod].get_node('/', '3')[otaz-1,dtaz-1]/100.0
        return (t,d,f)
                    

