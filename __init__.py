bl_info = {
    "name": "MIDI to Keyframes",
    "description": "Import MIDI files and generate animation keyframes",
    "author": "whoisryosuke",
    "version": (0, 0, 5),
    "blender": (2, 80, 0), # not sure if this is right
    "location": "Properties > Output",
    "warning": "Make sure to press 'Install dependencies' button in the plugin panel before using", # used for warning icon and text in addons panel
    "wiki_url": "https://github.com/whoisryosuke/blender-midi-keyframes",
    "tracker_url": "",
    "category": "Development"
}


import bpy
from bpy.props import (StringProperty,
                       FloatProperty,
                       EnumProperty,
                       PointerProperty,
                       IntProperty,
                       CollectionProperty,
                       )
from bpy.types import (
                       PropertyGroup,
                       )
import math
import subprocess
import sys
import os

# Constants

DEFAULT_TEMPO = 500000

# Global state
midi_file_loaded = ""
selected_tracks_raw = []

def handle_midi_file_path(midi_file_path):
    fixed_midi_file_path = midi_file_path

    # Relative file path? Lets fix that
    if "//" in midi_file_path:
        filepath = bpy.data.filepath
        directory = os.path.dirname(filepath)
        midi_path_base = midi_file_path.replace("//", "")
        fixed_midi_file_path = os.path.join( directory , midi_path_base)
        
    return fixed_midi_file_path
    

# ------------------------------------------------------------------------
#    Scene Properties
# ------------------------------------------------------------------------


def selected_track_enum_callback(scene, context):
    global midi_file_loaded, selected_tracks_raw

    midi_keyframe_props = context.scene.midi_keyframe_props
    midi_file_path = midi_keyframe_props.midi_file
    
    if not has_valid_midi_file(context):
        return []

    # Have we already scanned this file? Check the "cache"
    if midi_file_loaded == midi_file_path:
        return selected_tracks_raw

    # Import the MIDI file
    from mido import MidiFile

    fixed_path = handle_midi_file_path(midi_file_path)
    mid = MidiFile(fixed_path)

    # Setup time for track
    selected_tracks_raw = []
    time = 0
    # current_frame = context.scene.frame_current
    scene_start_frame = context.scene.frame_start
    scene_end_frame = context.scene.frame_end
    total_frames = scene_end_frame - scene_start_frame
    

    # Determine active track
    for i, track in enumerate(mid.tracks):
        # Loop over each note in the track
        for msg in track:
            if not msg.is_meta:
                # add to list of tracks
                selected_tracks_raw.insert(len(selected_tracks_raw), ("{}".format(i), "Track {} {}".format(i, track.name), ""))
                break;

    # print(selected_tracks_raw)

    # Mark this MIDI file as "cached"
    midi_file_loaded = midi_file_path
    
    return selected_tracks_raw

# Key object item
class KeyItem(PropertyGroup):
    name: StringProperty(
        name="Note Name",
        description="Name of the key's playing note",
    )
    obj: PointerProperty(
        name="Object Reference",
        description="Reference to the key 3d object",
        type=bpy.types.Object,
    )

class KeyList(bpy.types.UIList):
    bl_label = "UIList for Keymapping"
    bl_idname = "KeyList"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.label(text=item.name)
            row.prop(item, "obj", text="")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.prop(item.obj)

# UI properties
class GI_SceneProperties(PropertyGroup):
        
    # User Settings
    
    # MIDI File data
    midi_file: StringProperty(
        name="MIDI File",
        description="Music file you want to import",
        subtype = 'FILE_PATH'
        )
    selected_track:EnumProperty(
        name="Selected Track",
        description="The track you want copied to animation frames",
        items=selected_track_enum_callback
        )
    midi_file_loaded = ""
    
    # Animation toggles
    travel_distance: FloatProperty(
        name = "Travel Distance",
        description = "How far key moves when 'pressed' or how high object 'jumps'",
        default = 1.0,
        min = 0.01,
        max = 100.0
        )
    animation_type: EnumProperty(
        name="Object Animation",
        description="Changes what animates about object (e.g. Move is up and down)",
        items=[ ('MOVE', "Move", ""),
                ('SCALE', "Scale", ""),
                ('ROTATE', "Rotate", ""),
              ]
        )
    axis: EnumProperty(
        name="Axis",
        description="Axis that gets animated, aka direction piano keys move",
        items=[ ('0', "X", ""),
                ('1', "Y", ""),
                ('2', "Z", ""),
              ]
        )
    direction: EnumProperty(
        name = "Direction",
        description = "Do the objects move up or down?",
        items=[ ('down', "Down", ""),
                ('up', "Up", ""),
              ]
        )
    octave: EnumProperty(
        name = "Octave",
        description = "Which octave should we use? (e.g. 3 = C3, D3, etc)",
        items=[ ('0', "All", ""),
                ('1', "1", ""),
                ('2', "2", ""),
                ('3', "3", ""),
                ('4', "4", ""),
                ('5', "5", ""),
                ('6', "6", ""),
                ('7', "7", ""),
                ('8', "8", ""),
              ]
        )
    speed: FloatProperty(
            name = "Speed",
            description = "Controls the tempo by this rate (e.g. 2 = 2x slower, 0.5 = 2x faster)",
            default = 1.0,
            min = 0.01,
            max = 100.0
        )

    # MIDI Keys
    obj_jump: PointerProperty(
        name="Jumping Object",
        description="Object that 'jumps' between key objects",
        type=bpy.types.Object,
        )

    keys: CollectionProperty(
        name="Key Object List",
        description="List of piano key objects to animate with midi events",
        type=KeyItem,

    )

    selected_key: IntProperty(
        name="Selected Key ID",
        description="ID of selected key list item",
    )
    
    # App State (not for user)
    initial_state = {}

# UI Panel
class GI_GamepadInputPanel(bpy.types.Panel):
    """Creates a Panel in the scene context of the properties editor"""
    bl_category = "MIDI Import"
    bl_label = "MIDI Importer"
    bl_idname = "SCENE_PT_gamepad"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    # bl_context = "output"
    
    def draw(self, context):
        layout = self.layout

        scene = context.scene
        midi_keyframe_props = scene.midi_keyframe_props
        
        # Legacy: Install deps using pip - we keep deps as git submodules now
        # layout.operator("wm.install_midi")

        layout.label(text="MIDI Settings", icon="OUTLINER_OB_SPEAKER")
        layout.prop(midi_keyframe_props, "midi_file")
        layout.prop(midi_keyframe_props, "selected_track")
        layout.prop(midi_keyframe_props, "octave")

        layout.separator(factor=1.5)
        layout.label(text="Animation Settings", icon="IPO_ELASTIC")

        if midi_keyframe_props.animation_type != "SCALE":
            layout.prop(midi_keyframe_props, "axis")
        
        layout.prop(midi_keyframe_props, "travel_distance")
        layout.prop(midi_keyframe_props, "animation_type")
        layout.prop(midi_keyframe_props, "direction")
        layout.prop(midi_keyframe_props, "speed")

        layout.separator(factor=1.5)
        layout.label(text="Generate Animation", icon="RENDER_ANIMATION")
        layout.operator("wm.generate_piano_animation")
        layout.operator("wm.generate_jumping_animation")

        layout.separator(factor=1.5)
        layout.label(text="Piano Keys", icon="OBJECT_DATAMODE")
        layout.operator("wm.assign_keys")
        layout.operator("wm.initialise_key_list")
        layout.template_list("KeyList", "key-list", midi_keyframe_props, "keys", midi_keyframe_props, "selected_key")

        layout.separator(factor=1.5)
        layout.label(text="Other Objects", icon="OBJECT_HIDDEN")
        layout.prop(midi_keyframe_props, "obj_jump", icon="MATSPHERE")

        layout.separator(factor=4.2)
        layout.label(text="Danger Zone", icon="ERROR")
        layout.operator("wm.delete_all_keyframes", icon="TRASH")

class GI_install_midi(bpy.types.Operator):
    """Install mido"""
    bl_idname = "wm.install_midi"
    bl_label = "Install dependencies"
    bl_description = "Installs necessary Python modules for handling MIDI files"

    def execute(self, context: bpy.types.Context):

        print("Installing MIDI library...") 
        python_exe = os.path.join(sys.prefix, 'bin', 'python.exe')
        target = os.path.join(sys.prefix, 'lib', 'site-packages')

        subprocess.call([python_exe, '-m', 'ensurepip'])
        subprocess.call([python_exe, '-m', 'pip', 'install', '--upgrade', 'pip'])

        subprocess.call([python_exe, '-m', 'pip', 'install', '--upgrade', 'mido', '-t', target])

        return {"FINISHED"}
    
# Shared helper functions
def get_note_key(midi_keyframe_props, midi_note):
    keys = midi_keyframe_props.keys
    if len(keys) > midi_note - 21:
        note_key = keys[midi_note - 21]
        return note_key
    return None

def has_valid_midi_file(context) -> bool:
        midi_keyframe_props = context.scene.midi_keyframe_props
        midi_file_path = midi_keyframe_props.midi_file

        # Check input and ensure it's actually MIDI
        is_midi_file = ".mid" in midi_file_path
        # TODO: Return error to user somehow??
        if not is_midi_file:
            return False
        return True

def get_note_octave(midi_note):
    octave = round(midi_note / 12)
    return octave

class ParsedMidiFile:
    total_time = 0
    midi = None
    has_release = False
    tempo = DEFAULT_TEMPO
    selected_track = 0

    def __init__(self, midi_file_path, selected_track) -> None:
        print("Loading MIDI file...") 
        self.selected_track = selected_track
        from mido import MidiFile

        fixed_midi_file_path = handle_midi_file_path(midi_file_path)

        self.midi = MidiFile(fixed_midi_file_path)
        
        # Get tempo from the first track
        for msg in self.midi.tracks[0]:
            if msg.is_meta and msg.type == 'set_tempo':
                self.tempo = msg.tempo

        # Total time
        for msg in self.midi.tracks[int(selected_track)]:
            
            # Figure out total time
            # We basically loop over every note in the selected track
            # and add up the time!
            self.total_time += msg.time

            # We also see if there's any stopping points using `note_off`
            # If missing - we assume notes are held for 1 second (like 1 block in FLStudio)
            if msg.type == 'note_off':
                self.has_release = True

    def for_each_key(self, context, key_callback):
        from mido import tick2second

        scene_start_frame = context.scene.frame_start
        scene_end_frame = context.scene.frame_end
        total_frames = scene_end_frame - scene_start_frame
        fps = context.scene.render.fps
        time = 0
        midi_keyframe_props = context.scene.midi_keyframe_props
        speed = midi_keyframe_props.speed

        last_keyframe = 0
        last_note = None


        # Loop over each MIDI track
        for msg in self.midi.tracks[int(self.selected_track)]:
            # mido returns "metadata" embedded alongside music
            # we don't need so we filter out
            # print(msg.type)
            is_note = True if msg.type == "note_on" or msg.type == "note_off" else False
            if not msg.is_meta and is_note:
                pressed = True if msg.type == "note_on" else False
                released = True if msg.type == "note_off" else False

                # Figure out the actual note "letter" (e.g. C, C#, etc)
                octave = get_note_octave(msg.note)
                
                # Increment time
                time += msg.time
                # Figure out what frame we're on
                time_percent = time / self.total_time
                current_frame = total_frames * time_percent
                # print("time: {}, current frame: {}".format(time, current_frame))
                real_time = tick2second(time, self.midi.ticks_per_beat, self.tempo) * speed

                # print("real time in seconds", real_time)

                real_keyframe = (real_time * fps) + 1

                key_callback(context, msg.note, octave, real_keyframe, pressed, self.has_release, last_keyframe, last_note)

                last_keyframe = real_keyframe
                last_note = msg.note

class GI_generate_piano_animation(bpy.types.Operator):
    """Generate animation"""
    bl_idname = "wm.generate_piano_animation"
    bl_label = "Piano Key Animation"
    bl_description = "Creates keyframes on piano key objects to simulate playback"

    def execute(self, context: bpy.types.Context):
        midi_keyframe_props = context.scene.midi_keyframe_props
        midi_file_path = midi_keyframe_props.midi_file
        selected_track = midi_keyframe_props.selected_track
        animation_type = midi_keyframe_props.animation_type
        axis = int(midi_keyframe_props.axis)

        # Is it a MIDI file? If not, bail early
        if not has_valid_midi_file(context):
            return {"FINISHED"}


        # Import the MIDI file
        print("Parsing MIDI file...") 
        midi_file = ParsedMidiFile(midi_file_path, selected_track)

        # Debug - check for meta messages    
        # for msg in mid.tracks[int(selected_track)]:
        #     is_note = True if msg.type == "note_on" or msg.type == "note_off" else False
        #     if not is_note:
        #         print(msg)

        # Get initial positions for each key
        for key in context.scene.midi_keyframe_props.keys:
            # Get the right object corresponding to the note
            key_name = key.name
            move_obj = key.obj
            if move_obj == None:
                continue
            
            match animation_type:
                case "MOVE":
                    midi_keyframe_props.initial_state[key_name] = move_obj.location[axis]

                case "SCALE":
                    midi_keyframe_props.initial_state[key_name] = move_obj.scale.x
                    
                case "ROTATE":
                    midi_keyframe_props.initial_state[key_name] = move_obj.rotation_euler[axis]

        # Loop over each music note and animate corresponding keys
        midi_file.for_each_key(context, animate_keys)

        return {"FINISHED"}

class GI_delete_all_keyframes(bpy.types.Operator):
    """Deletes all keyframes with confirm dialog"""
    bl_idname = "wm.delete_all_keyframes"
    bl_label = "Delete All Keyframes"
    bl_description = "Clears all animation data from assigned key objects"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return True
    def execute(self, context: bpy.types.Context):
        midi_keyframe_props = context.scene.midi_keyframe_props

        for key in midi_keyframe_props.keys:
            note_obj = key.obj
            if note_obj == None:
                continue
            note_obj.animation_data_clear()

        return {"FINISHED"}
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

class GI_assign_keys(bpy.types.Operator):
    """Test function for gamepads"""
    bl_idname = "wm.assign_keys"
    bl_label = "Auto-Assign Keys"
    bl_description = "Finds piano keys in currently selected collection"

    def execute(self, context: bpy.types.Context):
        midi_keyframe_props = context.scene.midi_keyframe_props

        for check_obj in context.collection.all_objects:
            obj_name_split = check_obj.name.split(".")
            obj_name_key = obj_name_split[-1]
            for key in midi_keyframe_props.keys:
                names = key.name.split("/")
                for name in names:
                    if name == obj_name_key:
                        key.obj = check_obj

        return {"FINISHED"}

class GI_generate_jumping_animation(bpy.types.Operator):
    """Jump animation"""
    bl_idname = "wm.generate_jumping_animation"
    bl_label = "Jumping Animation"
    bl_description = "(BETA) Creates keyframes on Jump object animating between keys"

    def execute(self, context: bpy.types.Context):
        midi_keyframe_props = context.scene.midi_keyframe_props
        midi_file_path = midi_keyframe_props.midi_file
        selected_track = midi_keyframe_props.selected_track

        # Is it a MIDI file? If not, bail early
        if not has_valid_midi_file(context):
            return {"FINISHED"}

        # Do we have an object to move?
        if midi_keyframe_props.obj_jump == None:
            return {"CANCELLED"}

        # Import the MIDI file
        print("Parsing MIDI file...") 
        midi_file = ParsedMidiFile(midi_file_path, selected_track)

        # Debug - check for meta messages    
        # for msg in mid.tracks[int(selected_track)]:
        #     is_note = True if msg.type == "note_on" or msg.type == "note_off" else False
        #     if not is_note:
        #         print(msg)

        # Save initial keyframe
        midi_keyframe_props.obj_jump.keyframe_insert(data_path="location", frame=0)

        # Loop over each music note and animate corresponding keys
        midi_file.for_each_key(context, animate_jump)

        return {"FINISHED"}

class InitialiseKeyList(bpy.types.Operator):
    """Key Collection Initialise List"""
    bl_idname = "wm.initialise_key_list"
    bl_label = "Initialise Key List"
    bl_description = "Initialise keys list with object for all 88 piano keys"

    midi_notes = [
            ('21', "A0"),
            ('22', "A#0/Bb0"),
            ('23', "B0"),
            ('24', "C1"),
            ('25', "C#1/Db1"),
            ('26', "D1"),
            ('27', "D#1/Eb1"),
            ('28', "E1"),
            ('29', "F1"),
            ('30', "F#1/Gb1"),
            ('31', "G1"),
            ('32', "G#1/Ab1"),
            ('33', "A1"),
            ('34', "A#1/Bb1"),
            ('35', "B1"),
            ('36', "C2"),
            ('37', "C#2/Db2"),
            ('38', "D2"),
            ('39', "D#2/Eb2"),
            ('40', "E2"),
            ('41', "F2"),
            ('42', "F#2/Gb2"),
            ('43', "G2"),
            ('44', "G#2/Ab2"),
            ('45', "A2"),
            ('46', "A#2/Bb2"),
            ('47', "B2"),
            ('48', "C3"),
            ('49', "C#3/Db3"),
            ('50', "D3"),
            ('51', "D#3/Eb3"),
            ('52', "E3"),
            ('53', "F3"),
            ('54', "F#3/Gb3"),
            ('55', "G3"),
            ('56', "G#3/Ab3"),
            ('57', "A3"),
            ('58', "A#3/Bb3"),
            ('59', "B3"),
            ('60', "C4"),
            ('61', "C#4/Db4"),
            ('62', "D4"),
            ('63', "D#4/Eb4"),
            ('64', "E4"),
            ('65', "F4"),
            ('66', "F#4/Gb4"),
            ('67', "G4"),
            ('68', "G#4/Ab4"),
            ('69', "A4"),
            ('70', "A#4/Bb4"),
            ('71', "B4"),
            ('72', "C5"),
            ('73', "C#5/Db5"),
            ('74', "D5"),
            ('75', "D#5/Eb5"),
            ('76', "E5"),
            ('77', "F5"),
            ('78', "F#5/Gb5"),
            ('79', "G5"),
            ('80', "G#5/Ab5"),
            ('81', "A5"),
            ('82', "A#5/Bb5"),
            ('83', "B5"),
            ('84', "C6"),
            ('85', "C#6/Db6"),
            ('86', "D6"),
            ('87', "D#6/Eb6"),
            ('88', "E6"),
            ('89', "F6"),
            ('90', "F#6/Gb6"),
            ('91', "G6"),
            ('92', "G#6/Ab6"),
            ('93', "A6"),
            ('94', "A#6/Bb6"),
            ('95', "B6"),
            ('96', "C7"),
            ('97', "C#7/Db7"),
            ('98', "D7"),
            ('99', "D#7/Eb7"),
            ('100', "E7"),
            ('101', "F7"),
            ('102', "F#7/Gb7"),
            ('103', "G7"),
            ('104', "G#7/Ab7"),
            ('105', "A7"),
            ('106', "A#7/Bb7"),
            ('107', "B7"),
            ('108', "C8")
        ]

    def execute(self, context: bpy.types.Context):
        keys = context.scene.midi_keyframe_props.keys
        #TODO add modal to warn before clearing keys list
        keys.clear()
        for midi_note in InitialiseKeyList.midi_notes:
            key = keys.add()
            key.name = midi_note[1]
        return {"FINISHED"}

# Animates objects up and down like piano keys
def animate_keys(context, midi_note, octave: int, real_keyframe, pressed, has_release, prev_keyframe, prev_note):
    midi_keyframe_props = context.scene.midi_keyframe_props
    initial_state = midi_keyframe_props.initial_state
    animation_type = midi_keyframe_props.animation_type
    direction = midi_keyframe_props.direction
    direction_factor = -1 if direction == "down" else 1
    axis = int(midi_keyframe_props.axis)
    user_octave: str = midi_keyframe_props.octave

    # Skip this note if we don't care about the octave
    # 0 = All, so if it's not all, we need to check for octave
    if user_octave != "0":
        # The user_octave is string, while MIDI returns int for octave 
        if user_octave != str(octave):
            return;


    # Keyframe generation
    # Get the right object corresponding to the note
    key = get_note_key(midi_keyframe_props, midi_note)
    key_name = key.name
    move_obj = key.obj
    if move_obj == None:
        return
    
    # Save initial position as previous frame
    match animation_type:
        case "MOVE":
            move_obj.location[axis] = initial_state[key_name]
            move_obj.keyframe_insert(data_path="location", frame=real_keyframe - 1)

        case "SCALE":
            move_obj.scale = (initial_state[key_name],initial_state[key_name],initial_state[key_name])
            move_obj.keyframe_insert(data_path="scale", frame=real_keyframe - 1)
            
        case "ROTATE":
            move_obj.rotation_euler[axis] = initial_state[key_name]
            move_obj.keyframe_insert(data_path="rotation_euler", frame=real_keyframe - 1)

    # Move the object
    match animation_type:
        case "MOVE":
            # Position distance is negative for pressing (since we're in Z-axis going "down")
            # But it can be flipped by user preference
            reverse_direction = midi_keyframe_props.travel_distance * direction_factor
            move_distance = reverse_direction + initial_state[key_name] if pressed else initial_state[key_name]
            move_obj.location[axis] = move_distance
            move_obj.keyframe_insert(data_path="location", frame=real_keyframe)
        case "SCALE":
            # Scale "distance" is positive for pressing
            move_distance = midi_keyframe_props.travel_distance + initial_state[key_name] if pressed else initial_state[key_name]
            move_obj.scale = (move_distance,move_distance,move_distance)
            move_obj.keyframe_insert(data_path="scale", frame=real_keyframe)
        case "ROTATE":
            # Rotation distance is positive for pressing
            reverse_direction = midi_keyframe_props.travel_distance * direction_factor
            move_distance = reverse_direction + initial_state[key_name] if pressed else initial_state[key_name]
            move_obj.rotation_euler[axis] = math.radians(move_distance)
            move_obj.keyframe_insert(data_path="rotation_euler", frame=real_keyframe)

    # Does the file not have "released" notes? Create one if not
    # TODO: Figure out proper "hold" time based on time scale
    match animation_type:
        case "MOVE":
            move_obj.location[axis] = initial_state[key_name]
            move_obj.keyframe_insert(data_path="location", frame=real_keyframe + 10)
        case "SCALE":
            move_obj.scale = (initial_state[key_name],initial_state[key_name],initial_state[key_name])
            move_obj.keyframe_insert(data_path="scale", frame=real_keyframe + 10)
        case "ROTATE":
            move_obj.rotation_euler[axis] = initial_state[key_name]
            move_obj.keyframe_insert(data_path="rotation_euler", frame=real_keyframe + 10)

# Animates an object to "jump" between keys
def animate_jump(context, midi_note, octave, real_keyframe, pressed, has_release, prev_keyframe, prev_note):
    midi_keyframe_props = context.scene.midi_keyframe_props
    # Keyframe generation
    # Get the right object corresponding to the note
    piano_key = get_note_key(midi_keyframe_props, midi_note).obj
    if piano_key == None:
        return
    
    move_obj = midi_keyframe_props.obj_jump

    if pressed:
        piano_key_world_pos = piano_key.matrix_world.to_translation()

        # Create jumping keyframes in between
        if prev_note != None:
            frame_between = int((real_keyframe - prev_keyframe) / 2) + prev_keyframe
            # print("Jumping!!: {} {} {}".format(real_keyframe, prev_keyframe, frame_between))
            prev_piano_key = get_note_key(midi_keyframe_props, prev_note).obj
            prev_piano_key_world_pos = prev_piano_key.matrix_world.to_translation()
            middle_distance_x = (piano_key_world_pos.x - prev_piano_key_world_pos.x)
            move_obj.location.x = prev_piano_key_world_pos.x + middle_distance_x
            # print("middle point x", prev_piano_key_world_pos.x + middle_distance_x)
            move_obj.location.z += midi_keyframe_props.travel_distance
            move_obj.keyframe_insert(data_path="location", frame=frame_between)
            # print("Moving back down", note_letter, prev_note, prev_piano_key.name, prev_piano_key.location, prev_piano_key_world_pos.x, piano_key_world_pos.x)
            # Place it back down
            move_obj.location.z -= midi_keyframe_props.travel_distance


        # Move object to current key (the "down" moment)
        # print("pressed keyframe: {}".format(real_keyframe))
        # print("Setting jump keyframe: {} {}".format(piano_key.location.x, str(mathutils.Matrix.decompose(piano_key.matrix_world)[0])))
        # print("Setting jump keyframe: {} {}".format(note_letter, piano_key_world_pos.x))
        move_obj.location.x = piano_key_world_pos.x
        move_obj.keyframe_insert(data_path="location", frame=real_keyframe)



# Load/unload addon into Blender
classes = (
    KeyItem,
    KeyList,
    GI_SceneProperties,
    GI_GamepadInputPanel,
    GI_install_midi,
    GI_generate_piano_animation,
    GI_generate_jumping_animation,
    GI_assign_keys,
    GI_delete_all_keyframes,
    InitialiseKeyList,
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.Scene.midi_keyframe_props = PointerProperty(type=GI_SceneProperties)

def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)


if __name__ == "__main__":
    register()
