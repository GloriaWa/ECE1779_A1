import threading
import requests, datetime
import Frontend.config as conf

from flask import render_template, request, g, jsonify
from Frontend import webapp
from Frontend.Utilities import *

# Memcache host port
cache_host = "http://localhost:5001"

@webapp.before_first_request
def initial_settings():
    set_cache_parameter(conf.capacity, conf.strategy)
    t = threading.Thread(target=pollStatus)
    t.start()

def pollStatus():
    global cache_host

    while True:
        j = {}
        res = requests.post(cache_host + '/stats', json=j)
        time.sleep(5)

@webapp.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@webapp.route('/')
@webapp.route('/home')
def home():
    """ Main route, as well as default location for 404s
    """
    return render_template("home.html")

@webapp.errorhandler(404)
def not_found(e):
    return render_template("home.html")

@webapp.route('/add_img', methods=['GET', 'POST'])
def add_img():
    if request.method == 'POST':

        key = request.form.get('key')
        re = save_image(request, key)
        return render_template("add_img.html", result=re)

    return render_template("add_img.html")

@webapp.route('/show_image', methods=['GET', 'POST'])
def show_image():
    global cache_host

    if request.method == 'GET':
        return render_template('show_image.html')

    # POST, need to do some work here
    else:
        key = request.form.get('key')
        j = {"key": key}
        res = requests.post(cache_host + '/get', json=j)
        res = res.json()

        # if not in the cache -> cache miss!
        if (res['message'] == 'miss'):
            cnx = get_db()
            cursor = cnx.cursor(buffered=True)
            query = "SELECT ipath FROM img where ikey= %s"
            cursor.execute(query, (key,))

            # if the required img is in the db, get it / or else, error
            if (cursor._rowcount):
                img_ = str(cursor.fetchone()[0])

                # Need to close the db connection sooner!!! ********
                cnx.close()

                img = base64_img(img_)
                j = {"key":key, "img":img}
                res = requests.post(cache_host + '/put', json=j)

                return render_template('show_image.html', exists=True, img=img)

            # the required img is not in the db
            else:
                return render_template('show_image.html', exists=False, img="no exist")

        # cache hit
        else:
            return render_template('show_image.html', exists=True, img=res['img'])

@webapp.route('/key_list')
def key_list():
    global cache_host

    # get db key list
    cnx = get_db()
    cursor = cnx.cursor()
    query = "SELECT ikey FROM img"
    cursor.execute(query)
    db_keys = []

    for i in cursor:
        db_keys.append(i[0])
    db_key_no = len(db_keys)
    cnx.close()

    # get cache key list
    j = {}
    res = requests.post(cache_host + '/get_key_list', json=j)
    res = res.json()

    c_key_no = res['count']
    c_keys = res['keyList']

    if db_keys:
        return render_template('key_list.html', db_keys=db_keys, db_key_no=db_key_no, c_keys=c_keys, c_key_no=c_key_no)
    else:
        return render_template('key_list.html')

@webapp.route('/cache_stats')
def cache_stats():
    cnx = get_db()

    # Nice dictionary! Like it it make things easier...
    cursor = cnx.cursor(dictionary=True)

    stop_time = datetime.datetime.now()
    start_time = stop_time - datetime.timedelta(minutes=10)

    query = '''SELECT * FROM stats WHERE stime > %s and stime < %s'''
    cursor.execute(query, (start_time, stop_time))
    rows = cursor.fetchall()
    cnx.close()

    # get ready for plotting
    xx = []
    yy = {'item_count': [], 'request_count': [], 'hit_count': [], 'miss_count': [], 'cache_size': []}

    for r in rows:

        # prepare the data rows from the database and ready to draw graphs
        hit_count = r['request_count'] - r['miss_count']
        xx.append(r['stime'])

        yy['request_count'].append(r['request_count'])
        yy['miss_count'].append(r['miss_count'])
        yy['hit_count'].append(hit_count)
        yy['cache_size'].append(r['size'])
        yy['item_count'].append(r['item_count'])

    # plots
    plots = {}
    for i, values in yy.items():
        plots[i] = plot_graphs(xx, values, i)

    return render_template('cache_stats.html', cache_count_plot=plots['item_count'], cache_size_plot=plots['cache_size'],
                           request_count_plot=plots['request_count'], hit_count_plot=plots['hit_count'], miss_count_plot=plots['miss_count'])

@webapp.route('/memcache_config', methods=['GET', 'POST'])
def memcache_config():
    global cache_host
    cache_para = get_cache_parameter()

    if cache_para != None:
        capacity = cache_para[2]
        stra = cache_para[3]
    else:
        # Cannot query db, set to default
        capacity = 12
        stra = "LRU"

    if request.method == 'GET':
        return render_template('memcache_config.html', capacity=capacity, strategy=stra)

    # POST, need to do some work
    else:
        # if request to clear the cache
        if request.form.get("clear_cache") != None:
            requests.post(cache_host + '/clear')
            return render_template('memcache_config.html', capacity=capacity, strategy=stra, status="mem_clear")

        # else if request to clear ALL
        elif request.form.get("clear_all") != None:
            requests.post(cache_host + '/clear')

            cfolder = clear_folder()
            cdb = clear_db()

            return render_template('memcache_config.html', capacity=capacity, strategy=stra, status="all_clear")

        # else, take the new cache parameters
        else:
            new_cap = request.form.get('capacity')
            # log ##########################
            # print(new_cap)

            if new_cap.isdigit() and int(new_cap) <= 20:

                strategy_selected = request.form.get('replacement_policy')
                if strategy_selected == "Least Recently Used":
                    new_strategy = "LRU"
                else:
                    new_strategy = "RR"

                status = set_cache_parameter(new_cap, new_strategy)

                # if successs
                if status != None:
                    res = requests.post(cache_host + '/refreshConfiguration')
                    if res.json()['message'] == 'ok':
                        return render_template('memcache_config.html', capacity=new_cap, strategy=new_strategy, status="suc")

            # Error happen
            return render_template('memcache_config.html', capacity=capacity, strategy=stra, status="fail")


######### auto test api #########

@webapp.route('/api/delete_all', methods=['POST'])
def api_delete_all():
    requests.post(cache_host + '/clear')
    cfolder = clear_folder()
    cdb = clear_db()

    j = {"success": "true"}
    return (jsonify(j))

@webapp.route('/api/upload', methods=['POST'])
def upload():
    try:
        key = request.form.get('key')
        status = save_image(request, key)

        if status == "invalid" or status == "fail":
            j = {"success": "false", "error": {"code": "servererrorcode", "message": "Failed to upload the image"}}
            return (jsonify(j))

        j = {"success": "true", "key": key}
        return jsonify(j)

    except Exception as e:
        j = {"success": "false", "error": {"code": "servererrorcode", "message": "Error"}}
        return (jsonify(j))

@webapp.route('/api/list_keys', methods=['POST'])
def list_keys():
    try:
        cnx = get_db()
        cursor = cnx.cursor()
        query = "SELECT ikey FROM img"
        cursor.execute(query)

        keys = []
        for key in cursor:
            keys.append(key[0])
        cnx.close()

        j = {"success": "true", "keys": keys}
        return jsonify(j)

    except Exception as e:
        j = {"success": "false", "error": {"code": "servererrorcode", "message": "Error"}}
        return (jsonify(j))

@webapp.route('/api/key/<string:key_value>', methods=['POST'])
def single_key(key_value):
    try:
        j = {"key": key_value}
        res = requests.post('http://localhost:5001/get', json=j)
        res = res.json()

        # if not in the cache -> cache miss!
        if (res['message'] == 'miss'):
            cnx = get_db()
            cursor = cnx.cursor(buffered=True)
            query = "SELECT ipath FROM img where ikey= %s"
            cursor.execute(query, (key_value,))

            # if the required img is in the db, get it / or else, error
            if (cursor._rowcount):
                img_ = str(cursor.fetchone()[0])

                # Need to close the db connection sooner!!! ********
                cnx.close()

                img = base64_img(img_)
                j = {"key": key_value, "img": img}
                res = requests.post(cache_host + '/put', json=j)

                jj = {"success": "true", "key": key_value, "content": img}
                return (jsonify(jj))

            # the required img is not in the db
            else:
                jj = {"success": "false", "error": {"code": "servererrorcode", "message": "No such key"}}

        # cache hit
        else:
            j = {"success": "true", "key": key_value, "content": res['img']}
            return jsonify(j)

    except Exception as e:
        f = {"success": "false", "error": {"code": "servererrorcode", "message": "Error"}}
        return (jsonify(f))

