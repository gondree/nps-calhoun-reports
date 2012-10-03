#!/usr/bin/python

"""
Scrape metadata from NPS DSpace repository, Calhoun (http://calhoun.nps.edu)

"""
from datetime import date, timedelta, datetime
from oaipmh.client import Client
from oaipmh.metadata import MetadataRegistry, MetadataReader, oai_dc_reader
from optparse import OptionParser
import os, sys, pickle, pytz, re, urllib2
import codecs, latexcodec
import unittest

###############################################################################
#
# Constants
#
MISSING = 'MISSING'
BOM = unicode(codecs.BOM_UTF8, "utf8")

#
# Defaults
#
END = datetime.now(None)
START = END - timedelta(weeks=12)
SET_THESIS = 'hdl_10945_17'
URL = 'http://calhoun.nps.edu/oai/request'
OUTPUT = 'thesis_dump.tex'
RECORDS = []

###############################################################################
#
# The Qualified Dublin Core metadata Reader
#
qdc_reader = MetadataReader(
    fields = {
    'service':     ('textList', 'dc:description[@qualifier="service"]/text()'),
    'degree':      ('textList', 'dc:thesisdegree[@qualifier="level"]/text()'),
    'discipline':  ('textList', 'dc:thesisdegree[@qualifier="discipline"]/text()'),
    'school':      ('textList', 'dc:thesisdegree[@qualifier="grantor"]/text()'),
    'creator':     ('textList', 'dc:contributor[@qualifier="author"]/text()'),
    'advisor':     ('textList', 'dc:contributor[@qualifier="advisor"]/text()'),
    'degree-date': ('textList', 'dc:date[@qualifier="issued"]/text()'),
    'title':       ('textList', 'dc:title/text()'),
    'subject':     ('textList', 'dc:subject/text()'),
    'description': ('textList', 'dc:description/text()'),
    'publisher':   ('textList', 'dc:publisher/text()'),
    'contributor': ('textList', 'dc:contributor/text()'),
    'date':        ('textList', 'dc:date/text()'),
    'type':        ('textList', 'dc:type/text()'),
    'format':      ('textList', 'dc:format/text()'),
    'identifier':  ('textList', 'dc:identifier/text()'),
    'source':      ('textList', 'dc:source/text()'),
    'language':    ('textList', 'dc:language/text()'),
    'relation':    ('textList', 'dc:relation/text()'),
    'coverage':    ('textList', 'dc:coverage/text()'),
    'rights':      ('textList', 'dc:rights/text()')
    },
    namespaces = {
    'dc': 'http://purl.org/dc/elements/1.1/'
    }
)

###############################################################################
#
# NPS Report LaTeX macro constants
#   These are defined in preamble-calhoun.tex
#
NPSR = dict({'first-part':"\\npsrsectdegree{",
             'second-part':"\\npsrsectfield{",
             'title':"\\npsrtitle{",
             'creator':"\\npsrauthor{",
             'service':"\\npsrauthorservice{",
             'degree':"\\npsrdegree{",
             'degree-date':"\\npsrdegreedate{",
             'advisor':"\\npsradvisors{",
             'advisor-start':"\\npsradvisorbegin{}",
             'advisors-start':"\\npsradvisorsbegin{}",
             'description':"\\npsrabstract{",
             'subject':"\\npsrkeywords{",
             'url':"\\npsrurl{"
       })

###############################################################################
#
# Regex
#    Some complicated regular expressions used to massage Calhoun metadata
#

#
# '   A B C.' >>> 'A B C'
#
strip_ws_and_period = re.compile(r"""
    \s*                                         # <ws>
    (?P<rest>.+)                                # the rest
    (?=\s*[.]\s*)                               # .
    (?:\s*|)                                    # <ws>
    """, re.X | re.U)
#
# '(s) X' >>> 'X'
# 's X' >>> 'X'
#
strip_leading_junk = re.compile(r"""
    \s*                                         # <ws>
    (?:\(s\):|)                                 # opt: <'(s)'>
    (?:s,|)                                     # opt: <'s,'>
    (?P<rest>.+)                                # the rest
    """, re.X | re.U)
#
# '; <last>, <first>' >>> '<first> <last>'
# may be quite complex:
#  Smith-Jones, John-Jacob F., III.
# 
reverse_name = re.compile(r"""
    \s*(;\s|,\s)?\s*
    (?P<last>                             # last name:
        \w+[-\w]*\w+                        # word, hypenated word
        (\sJr\.|\sSr\.)?                    # optional: ' Jr.' or ' Sr.'
        (?=,\s)                             # look-ahead: ends w/ ', '
    )
    ,\s*                         # consume comma & ws
    (?P<suf1>                             # suffix:
        (?<=\s)                             # starts with \s
        [IVX]+                              # some combo of I, II, VII, etc
        (?=,\s)                             # look-ahead: ends w/ , or \s
    |)                                    # or, no suf1
    ,?\s*                        # consume comma & ws, if it exists
    (?P<first>                            # first name:
        \w+[.\w-]*\w+                       # word, hypenated word
        (?=\s|\.|)                          # follow: \s or '.' or nothing
    |   \w+ [.\w\s]* (\w | (?<=[A-Z])\.?)   # words / initials
        (?=\s)                              # look-ahead: ends w/ \s
    )
    \s*                          # consume ws
    (?P<mid>                              # middle name or middle initials:
        (?<=\s)                             # starts with \s
        \w+ [.\w\s]* (\w | (?<=[A-Z])\.?)   # words / initials
        (?=[,\s]?)                          # look-ahead: ends w/ ', ' or not
    |)                                    # or, no mid
    ,?\s*                        # consume comma & ws, if it exists
    (?P<suf2>                             # suffix:
        (?<=\s)                             # starts with \s
        [IVX]+                              # some combo of I, II, VII, etc
        (?=.|)                              # look-ahead: end w/ '.' or not
    |)                                    # or, no suf2
    \.?                          # consume trailing period, if it exists
    \s*
    """, re.X | re.U)
#
# '; <first> <last> ' >>> '<first> <last>'
# try to keep same logic as above
#
ordered_name = re.compile(r"""
    \s*(;\s|,\s)?\s*
    (?P<first>
        \w+[-\w]*\w+
        (?=\s)
    |   \w+ [.\w\s]* (\w | (?<=[A-Z])\.?)
        (?=\s)
    )
    \s*
    (?P<mid>
        (?<=\s)
        \w+ [.\w\s]* (\w | (?<=[A-Z])\.?)
        (?=\s)
    |)
    \s*
    (?P<last>
        (?<=\s)
        \w+[-\w]*\w+
        (\sJr\.|\sSr\.)?
    )
    (?P<suf1>
        (?<=\s)
        [IVX]+
    |)
    (?P<suf2>\s*|)                        # just here to define suf2
    \.?
    """, re.X | re.U)



###############################################################################
#
# Functions
#

def callback_parse_date(option, opt, value, parser, **kwargs):
    """
    Parses a date string into dateime
    """
    d = datetime.strptime(value, "%d/%m/%y")
    if kwargs['var'] == 'start':
        parser.values.start = d
    elif kwargs['var'] == 'end':
        parser.values.end = d
    return d


def clean_encode(v):
    """
    Cleans the identifiers 0xEF, 0xBB, 0xBF from unicode.
    These should not be present in a unicode stream, but
    but, alas, sometimes they are. We need to clean them out.
    We also encode the unicode as latex.
    """
    return v.replace(BOM,'').encode("latin1").encode("latex")


def parse_first_last(s):
    """
    Heuristically fixes names into 'first last' format, from a variety
    of formats found in Calhoun metadata. Returns a list [d1, d2, ...]
    where d1[0] is the 'First Last' version, and d1[1] is the 'Last, First'
    version (used for building our index).
    
    Opinion: Much of this is to filter "noise" generated by the library's 
    PDF scraping scripts,  because the thesis processor does not transition
    'good' metadata to the library, for NO REASON other than its own
    deficiencies / inefficiencies.
    """
    list = []
    str = ''

    # strip off initial garbage
    m = strip_leading_junk.match(s)
    next = m.start('rest')

    # process the rest, one 'chunk' (name) at a time
    while True:
        s = s[next:]
        fname = ''          # name in <First Last> order
        iname = ''          # name in <Last, First> order, for index
        if options.verbose:
            print "-> processing [%s]" % s

        # try to parse as 'Last, First'
        m = reverse_name.match(s)
        if not m:
            # if that fails, parse as 'First Last'
            m = ordered_name.match(s)
        if not m:
            break
        
        # got something to match, so try to process it
        if options.verbose:
            print "->", m.groups()

        first = m.group('first')
        mid = m.group('mid')
        last = m.group('last')
        suf1 = m.group('suf1')
        suf2 = m.group('suf2')
        
        # build fname
        if first:
            fname += first
        if mid:
            fname += ' ' + mid
        if last:
            fname += ' ' + last
        if suf1:
            fname += ' ' + suf1
        if suf2:
            fname += ' ' + suf2

        # build iname
        if last:
            iname += last + ','
        if first:
            iname += ' ' + first
        if mid:
            iname += ' ' + mid
        if suf1:
            iname += ', '  + suf1
        if suf2:
            iname += ', ' + suf2
        
        # add name to our list
        list.append([fname, iname])
        if options.verbose:
            print "-> [" + s + "] >>> [" + fname + "],[" + iname + "]"
        
        # advance to the next chunk
        next = m.end(len(m.groups()))

    if options.verbose:
        print "=>", list
    return list


def parse_service(s):
    """
    Strip 'author' and '(author)' and trailing whitespace and period
    to get the author service data.
    """
    m = strip_ws_and_period.match(s)
    if m:
        name = m.group('rest')
    else:
        name = s
    name = re.sub('\s\(?author\)?', '', name, flags=re.X | re.U)
    if options.verbose:
        print "=> [" + s + "] >>> [" + name + "]"
    return [name]


class TestParseCalhounMetadata(unittest.TestCase):
    """
    Unit tests for support functions associated with Calhoun metadata,
    specifically:
        * parse_first_last()
    """

    def test_name_a(self):
        """
        Examples of processing author names from Calhoun. Run these if you
        touch the Regex.
        """
        data = []
        data.append({'input': ' Brinfield, Gregory  ',
                     'ans'  : [['Gregory Brinfield', 
                                'Brinfield, Gregory']]})
        data.append({'input': ' Herbers, Thomas H.C. ',
                     'ans'  : [['Thomas H.C. Herbers', 
                                'Herbers, Thomas H.C.']]})
        data.append({'input': ' (s): Tsypkin, Mikhail. ',
                     'ans'  : [['Mikhail Tsypkin',
                                'Tsypkin, Mikhail']]})
        data.append({'input': ' (s): Lavoy, Peter R. ',
                     'ans'  : [['Peter R. Lavoy',
                                'Lavoy, Peter R.']]})
        data.append({'input': '  Darken, Rudolph ; Sullivan, Joseph A. ',
                     'ans'  : [['Rudolph Darken',
                                'Darken, Rudolph'],
                               ['Joseph A. Sullivan',
                                'Sullivan, Joseph A.']]})
        data.append({'input': 'Eitelberg, Mark J. ;  Crawford, Alice.',
                     'ans'  : [['Mark J. Eitelberg', 
                                'Eitelberg, Mark J.'],
                               ['Alice Crawford',
                                'Crawford, Alice']]})
        data.append({'input': 's, Kevin R. Gue, Ira Lewis.',
                     'ans'  : [['Kevin R. Gue', 
                                'Gue, Kevin R.'],
                               ['Ira Lewis', 
                                'Lewis, Ira']]})
        data.append({'input': 'Dorjjugder, Munkh-Ochir.',
                     'ans'  : [['Munkh-Ochir Dorjjugder',
                                'Dorjjugder, Munkh-Ochir']]})
        data.append({'input': 'Franck Jr., Raymond E.',
                     'ans'  : [['Raymond E. Franck Jr.',
                                'Franck Jr., Raymond E.']]})
        data.append({'input': 'Shing, Man-Tak ; Puett, Joseph F., III.',
                     'ans'  : [['Man-Tak Shing', 
                                'Shing, Man-Tak'],
                               ['Joseph F. Puett III', 
                                'Puett, Joseph F., III']]})
        data.append({'input': ' Maier, II, William B. ',
                     'ans'  : [['William B. Maier II',
                                'Maier, William B., II']]})
        data.append({'input': 'Chan, Hsiung Wei Roy.',
                     'ans'  : [['Hsiung Wei Roy Chan',
                                'Chan, Hsiung Wei Roy']]})
        data.append({'input': 'Yen, Chia-Chun.',
                     'ans'  : [['Chia-Chun Yen',
                                'Yen, Chia-Chun']]})
        data.append({'input': 'Newton, D. Adam.',
                     'ans'  : [['D. Adam Newton',
                                'Newton, D. Adam']]})
        data.append({'input': 'Lim, R. Augustus.',
                     'ans'  : [['R. Augustus Lim',
                                'Lim, R. Augustus']]})
        for d in data:
            out = parse_first_last(d['input'])
            self.assertEqual(len(out), len(d['ans']))
            for i in range(len(out)):
                self.assertEqual(out[i][0], d['ans'][i][0])
                self.assertEqual(out[i][1], d['ans'][i][1])

    def test_service_a(self):
        """ Examples of processing author's service metadata Calhoun """
        data = []
        data.append({'input': ' Ministry of Defense (author) civilian. ',
                     'ans'  : ['Ministry of Defense civilian']})

        data.append({'input': 'US Navy (USN) author.',
                     'ans'  : ['US Navy (USN)']})

        data.append({'input': 'Naval Postgraduate School author (civilian).',
                     'ans'  : ['Naval Postgraduate School (civilian)']})

        data.append({'input': ' Department of the Navy author (civilian). ',
                     'ans'  : ['Department of the Navy (civilian)']})
        for d in data:
            out = parse_service(d['input'])
            self.assertEqual(len(out), len(d['ans']))
            for i in range(len(out)):
                self.assertEqual(out[i], d['ans'][i])

def latexify_theses():
    """
    Turn the collected records into something that can be used by the 
    latex report template.
    """
    collection = dict({})
    str = ''

    for r in RECORDS:
        v = clean_encode(r['type'][0])
        if v and options.type and v != options.type:
            print "%% %s is not %s" % (r['handle'], options.type)
            continue
        v = clean_encode(r['degree-date'][0]) 
        if v and options.grad and v != options.grad:
            print "%% %s is from %s, not %s" % (r['handle'], v, options.grad)
            continue

        k1 = r['degree']
        k2 = r['discipline']
        if not k1:
            k1 = MISSING
        if not k2:
            k2 = MISSING
        k1 = clean_encode(k1[0])
        k2 = clean_encode(k2[0])
        
        if not k1 in collection.keys():
            collection[k1] = dict({})
        if not k2 in collection[k1]:
            collection[k1][k2] = []
        collection[k1][k2].append(r)
    #
    # first_part
    # 'Master of Science', 'Master of Arts', ... alphabetic sorted
    # 
    first_part = sorted(collection.keys())
    
    for k1 in first_part:
        print NPSR['first-part'], k1, '}',
        #
        # second_part
        # 'Applied Mathematics', 'Computer Science', ... alphabetic sorted
        # 
        second_part = sorted(collection[k1].keys()) 
        for k2 in second_part:
            print NPSR['second-part'], k1, "in", k2, '}{', k2,'}',
            #
            # record, alphabetic sort
            #
            sections = sorted(collection[k1][k2], key=lambda r: r['title'])
            for r in sections: 
                #
                # Parse, clean, latex-encode records
                #
                title    = [clean_encode(x) for x in r['title']]
                creator  = [clean_encode(x) for x in r['creator']]
                creator  = [parse_first_last(x) for x in creator]
                service  = [clean_encode(x) for x in r['service']]
                service  = [parse_service(x) for x in service]
                degrees  = [clean_encode(x) for x in r['degree']]
                dfields  = [clean_encode(x) for x in r['discipline']]
                degdate  = [clean_encode(x) for x in r['degree-date']]
                advisor  = [clean_encode(x) for x in r['advisor']]
                advisor  = [parse_first_last(x) for x in advisor]
                abstract = [clean_encode(x) for x in r['description']]
                subjects = [clean_encode(x) for x in r['subject']]
                if not title:
                    title = [MISSING]
                if not creator:
                    creator = [[MISSING, MISSING]]
                else:
                    creator = creator[0]
                if not service:
                    service = [MISSING for a in creator]
                else:
                    service = service[0]
                if not degrees:
                    degrees = [MISSING for a in creator]
                if not dfields:
                    dfields = [MISSING for a in creator]
                if not degdate:
                    degdate = [MISSING for a in creator]
                if not abstract:
                    abstract = [MISSING]
                if not subjects:
                    subjects = [MISSING]
                if not advisor:
                    advisor = [[MISSING, MISSING]]
                else:
                    advisor = advisor[0]

                # Print out the record with the latex syntax
                #
                line = [NPSR['title'], title[0], '}']
                print str.join(line),
                for i, x in enumerate(creator):
                    line = [NPSR['creator'], creator[i][0], '}{',
                                             creator[i][1] ,'}',
                            NPSR['service'], service[i], '}',
                            NPSR['degree'], degrees[i], " in ", dfields[i], '}',
                            NPSR['degree-date'], degdate[i], '}']
                    print str.join(line),

                if len(advisor) == 1:
                    print NPSR['advisor-start'],
                else:
                    print NPSR['advisors-start'],

                for i, x in enumerate(advisor):
                    line = [NPSR['advisor'], advisor[i][0], '}{',
                                             advisor[i][1], '}']
                    print str.join(line),
                    if i < len(advisor)-1:
                        sys.stdout.softspace=False
                        print ',',

                line = [NPSR['description'], abstract[0], '}']
                print str.join(line),
                
                print NPSR['subject'],
                for i, x in enumerate(subjects):
                    print x,
                    if i < len(subjects)-1:
                        sys.stdout.softspace=False
                        print ',',
                print '}',
                
                line = [NPSR['url'], r['handle'], '}']
                print str.join(line)


def scrape(start=START, end=END, set=SET_THESIS, type='Thesis'):
    """
    Create an OAI-PMH client, gather metadata and output it.

    """    
    total = num = 0
    msg = "Fetching records between " + str(start) + " and " + str(end)
    sys.stderr.write(msg + "\n")

    #
    # Set up metadata readers
    #
    registry = MetadataRegistry()
    registry.registerReader('oai_dc', oai_dc_reader)
    registry.registerReader('qdc', qdc_reader)
    # registry.registerReader('rdf', rdf_reader)   # no reader yet
    # registry.registerReader('ore', ore_reader)   # no reader yet
    # registry.registerReader('mets', mets_reader) # no reader yet

    client = Client(URL, registry)
    records = client.listRecords(metadataPrefix='qdc',
                                 from_=start, until=end, set=set)
    for (h, m, a) in records:
        if not m:
            sys.stderr.write("o")
            continue
        total = total + 1
        
        handle = m.getField('identifier')
        if not handle:
            sys.stderr.write("Record without a handle.\n")
            continue

        r = dict({ 'handle' : handle[0] })
        for key in qdc_reader._fields.keys():
           r[key] = m.getField(key)
        RECORDS.append(r)

        sys.stderr.write('.')
        sys.stderr.flush()
        num = num + 1
    msg = "\nCollected " + str(num) + " records, out of " + str(total)
    sys.stderr.write('\n' + msg + '\n');

    if options.store:
        pickle.dump(RECORDS, open(options.store, "wb"))


###############################################################################
#
# Main
#

parser = OptionParser()
parser.add_option("--verbose", "-v", dest="verbose",
                  default=False, action="store_true",
                  help="verbose messages, for debugging only")
parser.add_option("--test", dest="test",
                  default=False, action="store_true",
                  help="run automated tests")
parser.add_option("--from","--start", dest="start", 
                  default=START, metavar="DD/MM/YY", type="string",
                  action="callback", callback=callback_parse_date,
                  callback_kwargs = dict({'var':'start'}),
                  help="earliest record to scan (default = 12 weeks ago")
parser.add_option("--until","--end", dest="end",
                  default=END, metavar="DD/MM/YY", type="string",
                  action="callback", callback=callback_parse_date,
                  callback_kwargs = dict({'var':'end'}),
                  help="latest record to scan (dafult = today)")
parser.add_option("--grad", dest="grad",
                  default=None, metavar="YYYY-MM", type="string",
                  help="only include records matching this publication date")
parser.add_option("--set", dest="set",
                  default=SET_THESIS,
                  help="search this set on Calhoun (detault = NPS Theses)")
parser.add_option("--type", dest="type",
                  default="Thesis", metavar="RECORD",
                  help="filter on record type (detault = Thesis)")
parser.add_option("--output", "-o",
                  dest="output", metavar="FILE",
                  help="send stdout to file")
parser.add_option("--input", "-i",
                  dest="input", metavar="FILE",
                  help="read input from file")
parser.add_option("--store", "-s",
                  dest="store", metavar="FILE",
                  help="collected records (pickled) stored to file")

(options, args) = parser.parse_args()



if __name__=="__main__":
    if options.output:
        sys.stdout = open(options.output, 'w')

    if options.test:
        tl = unittest.TestLoader()
        suite = tl.loadTestsFromTestCase(TestParseCalhounMetadata)
        unittest.TextTestRunner(verbosity=2).run(suite)
        exit(0);

    if options.input:
        RECORDS = pickle.load( open(options.input, "rb") )
    else:
        scrape(start=options.start, end=options.end,
               set=options.set, type=options.type)
    latexify_theses()
