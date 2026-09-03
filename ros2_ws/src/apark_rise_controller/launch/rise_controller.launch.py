import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    # Layers three YAML files onto the node via --params-file arguments (NOT ROS
    # parameters - the node reads YAML directly, see apark_rise_node.py): this
    # package's own controller-tuning YAML, plus two files borrowed from
    # aero_common so origin_r and the safety envelope stay a single source of
    # truth shared with px4_telemetry / px4_teleop / px4_safety_lib instead of
    # being duplicated (and drifting) here. Later files win. Keys in those files
    # that this node never reads are silently ignored.
    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(get_package_share_directory('apark_rise_controller'), 'param', 'baseline_params_1.yaml'),
        description='Controller-tuning YAML under apark_rise_controller/param/.'
    )
    namespace_arg = DeclareLaunchArgument(
        'namespace',
        default_value='homebrew_0',
        description='Must match the namespace MAVROS was launched under (see singleagent_homebrew_teleop.launch.py).'
    )

    apark_rise_node = Node(
        package='apark_rise_controller',
        executable='apark_rise_controller',
        name='apark_rise_node',
        namespace=LaunchConfiguration('namespace'),
        arguments=[
            '--params-file', LaunchConfiguration('params_file'),
            '--params-file', os.path.join(get_package_share_directory('px4_telemetry'), 'param', 'park_coordinates.yaml'),
            '--params-file', os.path.join(get_package_share_directory('px4_safety_lib'), 'param', 'safety_config.yaml'),
        ],
        output='screen'
    )

    return LaunchDescription([params_file_arg, namespace_arg, apark_rise_node])
