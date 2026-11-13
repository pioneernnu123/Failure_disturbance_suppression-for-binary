
import gdb

function_bps   = {}
function_names = {}
current_finish = None
output_fd      = None
output_fname   = None
saved_trace    = None

class ResDumperCommand(gdb.Command):
    """various commands for automatic dumping of function results"""

    def __init__(self):
        super(ResDumperCommand, self).__init__("resdumper",
                                               gdb.COMMAND_SUPPORT,
                                               gdb.COMPLETE_NONE, True)

ResDumperCommand()

class RDAdd(gdb.Command):
    """add a function to the dump list"""

    global function_names

    def __init__(self):
        super(RDAdd, self).__init__("resdumper add",
                                     gdb.COMMAND_SUPPORT,
                                     gdb.COMPLETE_SYMBOL)

    def invoke(self, arg, from_tty):

        sym = gdb.lookup_symbol(arg)
        if sym[0] == None:

            function_names[arg] = 1 # dummy value
            print "Remembering symbol '%s' for later addition" % arg

        else:

            bp = gdb.Breakpoint(arg)
            function_bps[bp] = arg

RDAdd()

class RDFile(gdb.Command):
    """set the ResultDumper output file"""

    global output_fname

    def __init__(self):
        super(RDFile, self).__init__("resdumper file",
                                     gdb.COMMAND_SUPPORT,
                                     gdb.COMPLETE_FILENAME)

    def invoke(self, arg, from_tty):
        global output_fname

        output_fname = arg

RDFile()

def new_objfile_event(ev):
    global function_bps
    global function_names

    delnames = []

    for fn in function_names.iterkeys():
        sym = gdb.lookup_global_symbol(fn)
        if sym != None:
            bp = gdb.Breakpoint(fn)
            function_bps[bp] = fn
            delnames.append(fn)

    for fn in delnames:
        del function_names[fn]

gdb.events.new_objfile.connect(new_objfile_event)    

def stop_event(ev):
    global function_bps
    global current_finish
    global output_fname
    global saved_trace

    if isinstance(ev, gdb.BreakpointEvent):

        found_bp = None

        for bp in ev.breakpoints:
            if bp in function_bps:
                found_bp = bp
                break

            if bp == current_finish:
                found_bp = bp

        if not found_bp:
            print ev.breakpoint.expression
            print "The breakpoint wasn't in the list"
            return

        if isinstance(found_bp, gdb.FinishBreakpoint):
            current_finish = None

            if output_fname == None:
                return

            try:
                fd = open(output_fname, "a")
            except IOError:
                print "Unable to open file '%s' for writing" % output_fname
                return

            fd.write("---- return value '%s'\n" % found_bp.return_value)
            fd.write(saved_trace)
            fd.close()

        else:

            if current_finish != None:
                print "WARNING: There seems to be a finish-bp already?"

            current_finish = gdb.FinishBreakpoint()

            saved_trace = gdb.execute("bt", False, True)

        gdb.execute("continue")

    else:
        print "Other type of stop event"

gdb.events.stop.connect(stop_event)

