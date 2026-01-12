import os
from tables import open_file

class SkimException(Exception):
    """
    This class is used to communicate Skim errors.
    """
    pass


class Skim:
    """
    Base skim class.  Not sure what code will go in here or if it's just an API.
    """

    #: the time period codes
    TIMEPERIOD_NUM_TO_STR = { 1:"EA", 2:"AM", 3:"MD", 4:"PM", 5:"EV" }

    #: the purpose codes
    PURPOSE_NUM_TO_STR = { 1:"Work",    2:"GradeSchool", 3:"HighSchool",
                           4:"College", 5:"Other",       6:"WorkBased" }
        
    def __init__(self, file_dir, file_names):
        """
        Opens the skim table file[s] in *file_dir*.  
        *file_names* should be a list.
        """
        
        # mapping of filename -> skim file
        self.skim_table_files = {}
        
        for file_name in file_names:
            full_file = os.path.join(file_dir, file_name)
            if not os.path.exists(full_file):
                raise SkimException("Skim: %s file doesn't exist" % full_file)

            self.skim_table_files[file_name] = open_file(full_file, mode="r")
    
    def __del__(self):
        """
        Closes the skim files
        """
        # print "Destructing Skim"
        filenames = list(self.skim_table_files.keys())
        
        for filename in filenames:
            self.skim_table_files[filename].close()
            del self.skim_table_files[filename]
        
    