import info
import os

import io
import re
import sys
import subprocess

class subinfo(info.infoclass):
    def setTargets(self):
        for ver in ["master"]:
            self.svnTargets[ver] = f"[git]https://github.com/owncloud/client|{ver}|"

        self.defaultTarget = 'master'
        self.description = "ownCloud Desktop Client"
        self.webpage = "https://owncloud.org"

    def setDependencies(self):
        self.buildDependencies["craft/craft-blueprints-owncloud"] = None
        self.buildDependencies["dev-utils/cmake"] = None
        self.buildDependencies["kde/frameworks/extra-cmake-modules"] = None
        self.buildDependencies["dev-utils/breakpad-tools"] = None
        self.runtimeDependencies["libs/zlib"] = None
        self.runtimeDependencies["libs/qt5/qtbase"] = None
        self.runtimeDependencies["libs/qt5/qttranslations"] = None
        self.runtimeDependencies["libs/qt5/qtsvg"] = None
        self.runtimeDependencies["libs/qt5/qtxmlpatterns"] = None
        self.runtimeDependencies["libs/qt5/qtwebkit"] = None
        self.runtimeDependencies["qt-libs/qtkeychain"] = None


        self.buildDependencies["dev-utils/peparser"] = None


        applicationExecutable = os.environ.get('ApplicationExecutable', 'owncloud')
        applicationShortname = os.environ.get('ApplicationShortname', 'owncloud')

        CraftCore.log.info(f'ApplicationExecutable: {applicationExecutable}')

        self.packageDependencyExeEntryPoints = [
            # Client files
            f'{applicationExecutable}',
            f'{applicationExecutable}cmd',
            #'owncloud_crash_reporter',
        ]

        self.packageDependencyLibEntryPoints = [
            'OCContextMenu',
            'OCOVerlays',

            f'{applicationShortname}/plugins/{applicationExecutable}sync_vfs_suffix',
            f'{applicationShortname}/plugins/{applicationExecutable}sync_vfs_win',

            # Qt plugins
            'imageformats/qgif',
            'imageformats/qico',
            'imageformats/qjpeg',
            'imageformats/qsvg',
            'platforms/qwindows',
            'sqldrivers/qsqlite'
        ]



from Package.CMakePackageBase import *

class Package(CMakePackageBase):
    def __init__(self):
        CMakePackageBase.__init__(self)
        self.subinfo.options.fetch.checkoutSubmodules = True

        # Pending PR to move to standard BUILD_TESTING: https://github.com/owncloud/client/pull/6917#issuecomment-444845521
        self.subinfo.options.configure.args = "-DUNIT_TESTING={testing} ".format(testing="ON" if self.buildTests else "OFF")

        if 'OWNCLOUD_CMAKE_PARAMETERS' in os.environ:
                self.subinfo.options.configure.args += os.environ['OWNCLOUD_CMAKE_PARAMETERS']

    def symbolsDir(self):
        return os.path.join(self.imageDir(), 'symbols')

    # Loosely based on https://chromium.googlesource.com/chromium/chromium/+/34599b0bf7a14ab21a04483c46ecd9b5eaf86704/components/breakpad/tools/generate_breakpad_symbols.py#92
    def dumpSymbols(self, binaryFile) -> bool:
        if os.path.basename(binaryFile) == 'icudt58.dll':
            CraftCore.log.warning(f'dump_symbols: {binaryFile} is blacklisted because it has no symbols')
            return False

        CraftCore.log.info('Dump symbols for: %s' % binaryFile)

        realpath = os.path.realpath(binaryFile)
        out = io.BytesIO()
        utils.system(['dump_syms', realpath], stdout=out)

        outBytes = out.getvalue()
        firstLine = str(outBytes.splitlines()[0], 'utf-8')
        CraftCore.log.info('Module line: %s' % firstLine)

        if firstLine.startswith("loadDataForPdb and loadDataFromExe failed for"):
            CraftCore.log.warning(f"Module does not contain debug symbols: {binaryFile}")
            return False

        regex = "^MODULE [^ ]+ [^ ]+ ([0-9aA-fF]+) (.*)"
        CraftCore.log.debug('regex: %s' % regex)
        moduleLine = re.match(regex, firstLine)
        CraftCore.log.debug('regex: %s' % moduleLine)
        outputPath = os.path.join(self.symbolsDir(), moduleLine.group(2),
                             moduleLine.group(1))

        if (not os.path.exists(outputPath)):
            os.makedirs(outputPath, exist_ok=True)

        symbolFileBasename = moduleLine.group(2).replace(".pdb", "")
        symbolFile = os.path.join(outputPath, "%s.sym" % symbolFileBasename)
        outputFile = open(symbolFile, 'wb')
        outputFile.write(outBytes)

        CraftCore.log.info('Writing symbols to: %s' % symbolFile)

        return True

    def install(self):
        if not CMakePackageBase.install(self):
            return False


        return True

    def createPackage(self):
        if not ('ENABLE_CRASHREPORTS' in os.environ) or not (os.environ['ENABLE_CRASHREPORTS'] == 'True'):
            CraftCore.log.info('ENABLE_CRASHREPORTS is not active. Not dumping symbols.')
            return TypePackager.createPackage(self)


        sep = '\\%s' % os.sep
        regex = r"symbols%s.*" % sep
        self.whitelist.append(re.compile(regex))

        dirs = [
            os.path.join(self.rootdir, 'bin'),
            os.path.join(self.imageDir(), 'bin'),
            os.path.join(self.rootdir, 'lib'),
            os.path.join(self.imageDir(), 'lib'),
            os.path.join(self.rootdir, 'plugins'),
            os.path.join(self.imageDir(), 'plugins'),
        ]

        deps = {}

        for entryPoint in self.subinfo.packageDependencyExeEntryPoints:
            parseDeps((entryPoint + ".exe"), deps, systemLibraries, dirs)

        for entryPoint in self.subinfo.packageDependencyLibEntryPoints:
            parseDeps((entryPoint + ".dll"), deps, systemLibraries, dirs)

        realDeps = []
        for (k, v) in deps.items():
          CraftCore.log.debug('%s: %s' % (k,v))
          if v:
            realDeps += [k]

        CraftCore.log.info('Real deps without system libraries:')
        CraftCore.log.info(realDeps)

        for f in realDeps:
            absoluteFilename = findFile(f, dirs)
            self.dumpSymbols(absoluteFilename)

        return TypePackager.createPackage(self)

    # Forked from CMakeBuildSystem.py to add exclusion regex
    def unittest(self):
        """running cmake based unittests"""

        self.enterBuildDir()

        command = ["ctest", "--output-on-failure", "--timeout", "300"]

        command += ["--exclude-regex", "WinVfsTest"]

        if CraftCore.debug.verbose() == 1:
            command += ["-V"]
        elif CraftCore.debug.verbose() > 1:
            command += ["-VV"]
        return utils.system(command)

# FIXME: replace with CraftCore.cache.getCommandOutput
def getCommandOutput(cmd):
  print(f"getCommandOutput: {cmd}")
  result = subprocess.run(cmd, stdout=subprocess.PIPE)
  return result.stdout.decode('utf-8')

def findFile(filename, dirs):
    for dir in dirs:
        absoluteFilename = os.path.join(dir, filename)
        if os.path.exists(absoluteFilename):
            return absoluteFilename
        #else:
        #    CraftCore.log.debug(f"{absoluteFilename} does not exist")

    return None


def parseDirectDeps(filename, dirs):
  print(f"parseDirectDeps: {filename} in {dirs}")
  absoluteFilename = findFile(filename, dirs)
  if not absoluteFilename:
    print(f"file not found: ${filename} in {dirs}")
    return []

  # HACK: Use CraftCore.cache.getCommandOutput instead
  return getCommandOutput([CraftCore.cache.findApplication("peparser"), '--imports', absoluteFilename]).splitlines()

def isSystemLibrary(filename, systemLibraries):
  filenameLower = filename.lower()
  if filenameLower in systemLibraries:
    return True

  if filenameLower.startswith('api-ms-win-crt-runtime'):
    return True

  if filenameLower.startswith('api-ms-win-crt'):
    return True

  return False


def parseDeps(filename, deps, systemLibraries, dirs):
  if not filename in deps:
    sysLib = isSystemLibrary(filename, systemLibraries)
    deps[filename] = not sysLib
    if not sysLib:
      absoluteFilename = findFile(filename, dirs)
      if not absoluteFilename:
        CraftCore.log.warning("File not found %s" % (filename))
        del deps[filename]
        return
      directDeps = parseDirectDeps(filename, dirs)
      CraftCore.log.debug("Print dep for dep %s %s" % (filename, directDeps))
      for dep in directDeps:
        parseDeps(dep, deps, systemLibraries, dirs)


systemLibraries = [
  'advapi32.dll',
  'bcrypt.dll',
  'cfgmgr32.dll',
  'comctl32.dll',
  'comdlg32.dll',
  'crypt32.dll',
  'd3d8.dll',
  'd3d9.dll',
  'ddraw.dll',
  'dnsapi.dll',
  'dsound.dll',
  'dwmapi.dll',
  'dxva2.dll',
  'evr.dll',
  'gdi32.dll',
  'gdiplus.dll',
  'glu32.dll',
  'glut32.dll',
  'imm32.dll',
  'iphlpapi.dll',
  'kernel32.dll',
  'ksuser.dll',
  'mf.dll',
  'mfplat.dll',
  'mpr.dll',
  'mscms.dll',
  'mscoree.dll',
  'msimg32.dll',
  'msvcr71.dll',
  'msvcr80.dll',
  'msvcr90.dll',
  'msvcrt.dll',
  'mswsock.dll',
  'netapi32.dll',
  'odbc32.dll',
  'ole32.dll',
  'oleacc.dll',
  'oleaut32.dll',
  'opengl32.dll',
  'psapi.dll',
  'rpcrt4.dll',
  'secur32.dll',
  'setupapi.dll',
  'shell32.dll',
  'shlwapi.dll',
  'user32.dll',
  'userenv.dll',
  'usp10.dll',
  'uxtheme.dll',
  'version.dll',
  'wininet.dll',
  'winmm.dll',
  'winspool.drv',
  'wldap32.dll',
  'ws2_32.dll',
  'wsock32.dll',
]

systemLibraries += ['msvcp140.dll', 'vcruntime140.dll']
