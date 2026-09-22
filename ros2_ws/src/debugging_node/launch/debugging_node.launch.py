import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

NAMESPACE='homebrew_sim_0'

def generate_launch_description():
    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(get_package_share_directory('debugging_node'), 'param', 'debugging_node.yaml'),
        description='YAML under debugging_node/param/.'
    )

    namespace_arg = DeclareLaunchArgument(
        'namespace',
        default_value=NAMESPACE,
        description='Must match the namespace MAVROS.'
    )

    apark_rise_node = Node(
        package='debugging_node',
        executable='debugging_node',
        name='debugging_node',
        namespace=LaunchConfiguration('namespace'),
        arguments=[
            '--params-file', LaunchConfiguration('params_file'),
        ],
        ros_arguments=['--log-level', 'info'],
        output='screen'
    )

    return LaunchDescription([params_file_arg, namespace_arg, apark_rise_node])
