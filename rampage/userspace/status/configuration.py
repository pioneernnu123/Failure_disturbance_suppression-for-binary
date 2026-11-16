'''
This source code is distributed under the MIT License

Copyright (c) 2010, Jens Neuhalfen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''

import mmap
import kpage
import struct
from contextlib import contextmanager
import fcntl
import os
import stat

from ctypes import *
import sys

# LZU DSLAB CHANGE

def _open_create( path, length):
    """ Open the file and make it the length passed. If the file does not exist, create it and fill it with 0"""
    f = None
    try:
        f = open(path, 'r+b')
    except:
        pass

    if not f:
        f = open(path, 'w+b')
    # LZU DSLAB CHANGE

    f.seek(int(length))
    f.truncate()
    f.seek(0)
    return f

class FileBasedConfiguration():
    '''
    Implements a memory-map- based configuration..
    - Each frame is represented by an instance of FrameStatus
    - The frames can be read by using the __getitem__ interface, indexing it by PFN
    - The fields inside the returned FrameStatus-instance directly map to the file, i.e.
       CHANGING THE INSTANCE CHANGES THE FILE

       E.g.: To update pfn 4711

       inst1 = cfg[4711]
       inst2 = cfg[4711]
       inst1.status = 12345
       print(inst2.status) # --> 12345
       inst2.status = 6789
       print(inst1.status) # --> 6789

    '''

    def __init__(self,  path, num_frames, instance_clazz):
        self.instance_clazz = instance_clazz
        self.num_frames = num_frames
        self.record_size = sizeof(instance_clazz)
        self.path = path
        self.file = None
        self.map = None

    def get_record_count(self):
        """
        Return the number of records in the file
        """
        return  self.num_frames

    def open(self):
        self.close()
        size = self.num_frames * self.record_size
        self.file = _open_create(self.path,  size)
        fileno = self.file.fileno()
        # LZU DSLAB CHANGE

        self.map = mmap.mmap(fileno, int(size))
        return self

    def open_sparse(self):
        """Open the same PFN-indexed file without truncating or mapping it."""
        self.close()
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("the PFN status file must be a regular file")
            self.file = os.fdopen(fd, 'r+b', buffering=0)
        except (OSError, ValueError):
            os.close(fd)
            raise
        return self

    @contextmanager
    def locked_records(self):
        fcntl.flock(self.file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self.file, fcntl.LOCK_UN)

    def read_record(self, pfn):
        data = os.pread(self.file.fileno(), self.record_size, pfn * self.record_size)
        return self.instance_clazz.from_buffer_copy(data.ljust(self.record_size, b'\0'))

    def write_record(self, pfn, record):
        if os.pwrite(self.file.fileno(), bytes(record), pfn * self.record_size) != self.record_size:
            raise OSError("incomplete write to the PFN status file")

    def close(self):
        if (self.map):
            self.map.close()
            self.map = None

        if (self.file):
            self.file.close()
            self.file = None

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def __getitem__(self, key):
        if not self.file:
            return None
        offset = key * self.record_size
        ret = self.instance_clazz.from_buffer(self.map, offset)

        return ret

