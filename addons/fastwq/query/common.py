#-*- coding:utf-8 -*-
#
# Copyright (C) 2018 sthoo <sth201807@gmail.com>
#
# Support: Report an issue at https://github.com/sth2018/FastWordQuery/issues
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version; http://www.gnu.org/copyleft/gpl.html.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from collections import defaultdict
import os
import io
import shutil
import unicodedata
from PyQt4 import QtGui
from aqt.utils import showInfo

from ..constants import Template
from ..context import config
from ..service import service_pool, QueryResult, copy_static_file
from ..service.base import LocalService
from ..utils import wrap_css


__all__ = [
    'InvalidWordException', 'update_note_fields',
    'update_note_field', 'promot_choose_css', 'add_to_tmpl',
    'query_all_flds', 'inspect_note'
]


class InvalidWordException(Exception):
    """Invalid word exception"""


def inspect_note(note):
    """
    inspect the note, and get necessary input parameters
    return word_ord: field index of the word in current note
    return word: the word
    return maps: dicts map of current note
    """

    conf = config.get_maps(note.model()['id'])
    maps_list = {'list': [conf], 'def': 0} if isinstance(conf, list) else conf
    maps = maps_list['list'][maps_list['def']]
    for i, m in enumerate(maps):
        if m.get('word_checked', False):
            word_ord = i
            break
    else:
        # if no field is checked to be the word field, default the
        # first one.
        word_ord = 0

    def purify_word(word):
        return word.strip() if word else ''

    word = purify_word(note.fields[word_ord])
    return word_ord, word, maps


def strip_combining(txt):
    "Return txt with all combining characters removed."
    norm = unicodedata.normalize('NFKD', txt)
    return u"".join([c for c in norm if not unicodedata.combining(c)])


def update_note_fields(note, results):
    """
    Update query result to note fields, return updated fields count.
    """

    if not results or not note or len(results) == 0:
        return 0
    count = 0
    for i, q in results.items():
        if isinstance(q, QueryResult) and i < len(note.fields):
            count += update_note_field(note, i, q)

    return count


def update_note_field(note, fld_index, fld_result):
    """
    Update single field, if result is valid then return 1, else return 0
    """

    result, js, jsfile = fld_result.result, fld_result.js, fld_result.jsfile
    # js process: add to template of the note model
    add_to_tmpl(note, js=js, jsfile=jsfile)
    # if not result:
    #     return
    if not config.force_update and not result:
        return 0

    value = result if result else ''
    if note.fields[fld_index] != value:
        note.fields[fld_index] = value
        return 1

    return 0


def promot_choose_css(missed_css):
    '''
    Choose missed css file and copy to user folder
    '''
    checked = set()
    for css in missed_css:
        filename = u'_' + css['file']
        if not os.path.exists(filename) and not css['file'] in checked:
            checked.add(css['file'])
            showInfo(
                Template.miss_css.format(
                    dict=css['title'],
                    css=css['file']
                )
            )
            try:
                filepath = css['dict_path'][:css['dict_path'].rindex(
                    os.path.sep)+1]
                filepath = QtGui.QFileDialog.getOpenFileName(
                    directory=filepath,
                    caption=u'Choose css file',
                    filter=u'CSS (*.css)'
                )
                if filepath:
                    shutil.copy(filepath, filename)
                    wrap_css(filename)

            except KeyError:
                pass


def add_to_tmpl(note, **kwargs):
    # templates
    '''
    [{u'name': u'Card 1', u'qfmt': u'{{Front}}\n\n', u'did': None, u'bafmt': u'',
        u'afmt': u'{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}\n\n{{12}}\n\n{{44}}\n\n', u'ord': 0, u'bqfmt': u''}]
    '''
    # showInfo(str(kwargs))
    afmt = note.model()['tmpls'][0]['afmt']
    if kwargs:
        jsfile, js = kwargs.get('jsfile', None), kwargs.get('js', None)
        if js and js.strip():
            addings = js.strip()
            if addings not in afmt:
                if not addings.startswith(u'<script') and not addings.endswith(u'/script>'):
                    addings = u'\n<script type="text/javascript">\n{}\n</script>'.format(addings)
                afmt += addings
        if jsfile:
            #new_jsfile = u'_' + \
            #    jsfile if not jsfile.startswith(u'_') else jsfile
            #copy_static_file(jsfile, new_jsfile)
            #addings = u'\r\n<script src="{}"></script>'.format(new_jsfile)
            jsfile = jsfile if isinstance(jsfile, list) else [jsfile]
            addings = u''
            for fn in jsfile:
                try:
                    f = io.open(fn, mode="r", encoding="utf-8")
                    addings += u'\n<script type="text/javascript">\n{}\n</script>'.format(f.read())
                    f.close()
                except:
                    pass
            if addings not in afmt:
                afmt += addings
        note.model()['tmpls'][0]['afmt'] = afmt


def query_all_flds(note):
    """
    Query all fields of single note
    """

    word_ord, word, maps = inspect_note(note)
    if not word:
        raise InvalidWordException

    if config.ignore_accents:
        word = strip_combining(unicode(word))

    # progress.update_title(u'Querying [[ %s ]]' % word)

    services = {}
    tasks = []
    for i, each in enumerate(maps):
        if i == word_ord:
            continue
        if i == len(note.fields):
            break
        #ignore field
        ignore = each.get('ignore', False)
        if ignore:
            continue
        #skip valued
        skip = each.get('skip_valued', False)
        if skip and len(note.fields[i]) != 0:
            continue
        #normal
        dict_unique = each.get('dict_unique', '').strip()
        dict_fld_ord = each.get('dict_fld_ord', -1)
        fld_ord = each.get('fld_ord', -1)
        if dict_unique and dict_fld_ord != -1 and fld_ord != -1:
            s = services.get(dict_unique, None)
            if s is None:
                s = service_pool.get(dict_unique)
                if s and s.support:
                    services[dict_unique] = s
            if s and s.support:
                tasks.append({'k': dict_unique, 'w': word,
                              'f': dict_fld_ord, 'i': fld_ord})

    success_num = 0
    result = defaultdict(QueryResult)
    for task in tasks:
        #try:
        service = services.get(task['k'], None)
        qr = service.active(task['f'], task['w'])
        if qr:
            result.update({task['i']: qr})
            success_num += 1
        #except:
        #    showInfo(_("NO_QUERY_WORD"))
        #    pass

    missed_css = list()
    for service in services.values():
        if isinstance(service, LocalService):
            for css in service.missed_css:
                missed_css.append({
                    'dict_path': service.dict_path,
                    'title': service.title,
                    'file': css
                })
        service_pool.put(service)

    return result, -1 if len(tasks) == 0 else success_num, missed_css
