import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'apark_rise_controller'

setup(
    name=package_name,
    version='0.3.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'param'), glob('param/*.yaml')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    zip_safe=True,
    maintainer='Max Gardenswartz',
    maintainer_email='mgardenswartz@ufl.edu',
    description='Second-order RISE controller for Autonomy Park',
    license='Apache-2.0',
    install_requires=[
        'setuptools',
    ],
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'apark_rise_controller = apark_rise_controller.apark_rise_node:main',
        ],
    },
)
