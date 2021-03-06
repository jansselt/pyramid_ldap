import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

requires = [
    'pyramid>=1.3a9',
    ]
if not 'READTHEDOCS' in os.environ:
    # hail mary for readthedocs
    # requires.extend(['ldappool', 'python3-ldap'])
    requires.extend(['python3-ldap'])

sampleapp_extras = [
    'waitress',
    'pyramid_debugtoolbar',
    ]
testing_extras = ['nose', 'coverage']
docs_extras = ['Sphinx']

setup(name='pyramid_ldap',
      version='0.1',
      description='pyramid_ldap',
      long_description=README + '\n\n' +  CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pylons",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Topic :: System :: Systems Administration :: Authentication/Directory :: LDAP",
        "License :: Repoze Public License",
        ],
      author='Chris McDonough',
      author_email='pylons-discuss@groups.google.com',
      url='http://pylonsproject.org',
      license="BSD-derived (http://www.repoze.org/LICENSE.txt)",
      keywords='web pyramid pylons ldap',
      packages=find_packages(),
      package_data={
      'pyramid_ldap': ['*.txt'],
      },
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=requires,
      extras_require = {
          'sampleapp':sampleapp_extras,
          'docs':docs_extras,
          'testing':testing_extras,
          },
      test_suite="pyramid_ldap",
      entry_points = """\
      [paste.app_factory]
      sampleapp = sampleapp:main
      """,
      )

