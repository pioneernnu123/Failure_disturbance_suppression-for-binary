
from tester.scanner_baseclass import ScannerBaseclass
import subprocess

class NoInject(ScannerBaseclass):
    def __init__(self, reporting):
        '''
        Constructor
        reporting.report_bad_memory(bad_offset, expected_value, actual_value)
        '''
        self.reporting = reporting   
    @staticmethod
    def name():
        return "noinject (external tool)"

    @staticmethod
    def shortname():
        return "noinject"

    def test(self, region, offset, length, physaddr):

        try:

            pass

        except Exception as e:

            return [offset]

        return []

ScannerBaseclass.register(NoInject)

