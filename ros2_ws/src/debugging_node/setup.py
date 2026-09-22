import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'debugging_node'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'param'), glob('param/*.yaml')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Max Gardenswartz',
    maintainer_email='mgardenswartz@ufl.edu',
    description='Node for testing offboard control modes in PX4 with MAVROS',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'debugging_node = debugging_node.debugging_node:main',
        ],
    },
)
