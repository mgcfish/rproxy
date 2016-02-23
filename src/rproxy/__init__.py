# (C) Amber Brown. See LICENSE for details.

from __future__ import absolute_import, division

import treq
import ConfigParser

from twisted.web import server
from twisted.python import usage
from twisted.application.service import Service
from twisted.web.resource import Resource
from twisted.python.filepath import FilePath
from twisted.application import service, strports

from ._version import __version__



class RProxyResource(Resource):

    isLeaf = True

    def __init__(self, hosts, letsEncryptPath, clacks):
        self._letsEncryptPath = letsEncryptPath
        self._clacks = clacks
        self._hosts = hosts

    def render(self, request):

        host = self._hosts.get(request.getRequestHostname().lower())

        if not host:
            request.code = 404
            request.responseHeaders.setRawHeaders("Server",
                                                  [__version__.package + " " + __version__.base()])
            return b"I can't seem to find a domain by that name. Look behind the couch?"

        if self._letsEncryptPath  and request.path == "/.well-known/acme-challenge":
            request.responseHeaders.setRawHeaders("Server",
                                                  [__version__.package + " " + __version__.base()])
            try:
                with self._letsEncryptPath.child(request.getRequestHostname()).child(".well-known").child("acme-challenge").open() as f:
                    return f.read()
            except:
                return b""

        if host["onlysecure"] and not request.isSecure():
            urlpath = request.URLPath()
            urlpath.scheme = "https"
            request.redirect(str(urlpath))
            return b""

        url = "{}://{}:{}/{}".format(
            "https" if host["proxysecure"] else "http",
            host["host"], host["port"], request.path[1:])

        d = treq.request(request.method, url,
                         headers=request.requestHeaders, data=request.content.getvalue())

        def write(res):

            request.code = res.code
            request.responseHeaders = res.headers
            request.responseHeaders.addRawHeader("X-Proxied-By",
                                                 __version__.package + " " + __version__.base())

            if self._clacks:
                request.responseHeaders.addRawHeader("X-Clacks-Overhead",
                                                     "GNU Terry Pratchett")

            g = treq.collect(res, request.write)
            g.addCallback(lambda _: request.finish())
            return g

        d.addCallback(write)

        return server.NOT_DONE_YET


class Options(usage.Options):
    optParameters = [
        ['config', None, 'rproxy.ini', 'Config.']
    ]


def makeService(config):

    ini = ConfigParser.RawConfigParser()
    ini.read(config['config'])

    rproxyConf = dict(ini.items("rproxy"))
    hostsConf = dict(ini.items("hosts"))

    hosts = {}

    for k, v in hostsConf.items():

        k = k.lower()
        hostname, part = k.rsplit("_", 1)

        if hostname not in hosts:
            hosts[hostname] = {}

        hosts[hostname][part] = v

    if not hosts:
        raise ValueError("No hosts configured.")

    for i in hosts:

        if "port" not in hosts[i]:
            raise ValueError("All hosts need a port.")

        if "host" not in hosts[i]:
            print("%s does not have a host, making localhost" % (i,))
            hosts[i]["host"] = "localhost"

        if "onlysecure" not in hosts[i]:
            print("%s does not have an onlysecure setting, making False" % (i,))
            hosts[i]["onlysecure"] = False

        if "proxysecure" not in hosts[i]:
            print("%s does not have an proxysecure setting, making False" % (i,))
            hosts[i]["proxysecure"] = False

        hosts[i]["onlysecure"] = True if hosts[i]["onlysecure"]=="True" else False
        hosts[i]["proxysecure"] = True if hosts[i]["proxysecure"]=="True" else False

        if hosts[i]["onlysecure"] and not hosts[i]["proxysecure"]:
            if not hosts[i].get("iamokwithalocalnetworkattackerpwningmyusers", "False") == "True":
                raise ValueError("%s has onlysecure==True, but proxysecure==False. This will mean TLS protected requests will not be TLS-protected between the proxy and the proxied server. If this is okay (e.g., if it's going over localhost), set %s_iamokwithalocalnetworkattackerpwningmyusers=True in your config." % (i, i))

        if hosts[i]["proxysecure"] and not hosts[i]["onlysecure"]:
            if not hosts[i].get("iamokwithlyingtomyproxiedserverthatheuserisoverhttps", "False") == "True":
                raise ValueError("%s has onlysecure==False, but proxysecure==True. This means that the connection may not be TLS protected between the user and this proxy, only the proxy and the proxied server. This can trick your proxied server into thinking the user is being served over HTTPS. If this is okay (I can't imagine why it is), set %s_iamokwithlyingtomyproxiedserverthatheuserisoverhttps=True in your config." % (i, i))

    if rproxyConf.get("letsencrypt"):
        letsEncryptPath = FilePath(rproxyConf.get("letsencrypt"))
    else:
        letsEncryptPath = None

    resource = RProxyResource(hosts, letsEncryptPath, rproxyConf.get("clacks"))

    site = server.Site(resource)

    multiService = service.MultiService()

    certificates = rproxyConf.get("certificates", None)

    if certificates:
        certificates = FilePath(certificates).path
        for i in rproxyConf.get("https_ports").split(","):
            print("Starting HTTPS on port " + i)
            multiService.addService(strports.service('txsni:' + certificates + ':tcp:' + i, site))

    for i in rproxyConf.get("http_ports", "").split(","):
        print("Starting HTTP on port " + i)
        multiService.addService(strports.service('tcp:' + i, site))

    return multiService


__all__ = ["__version__", "makeService"]