import Live
import os
from RemoteSLComponent import RemoteSLComponent
from consts import *
import rtmidi

class MixerController(RemoteSLComponent):
    """Represents the 'right side' of the RemoteSL:
    The sliders with the two button rows, and the transport buttons.
    All controls will be handled by this script: The sliders are mapped to volume/pan/sends
    of the underlying tracks, so that 8 tracks can be controlled at once.
    Banks can be switched via the up/down bottons next to the right display.
    """
    def __init__(self, remote_sl_parent, display_controller, c_instance):
        RemoteSLComponent.__init__(self, remote_sl_parent)
        self.__display_controller = display_controller
        self.__parent = remote_sl_parent
        self.__forward_button_down = False
        self.__rewind_button_down = False
        self.__c_instance = c_instance
        self.__strip_offset = 0
        self.__blink = 0
        self.__strips = [ MixerChannelStrip(self, i) for i in range(NUM_CONTROLS_PER_ROW) ]
        self.__assigned_tracks = []
        self.__transport_locked = False
        self.__lock_enquiry_delay = 0
        self.song().add_visible_tracks_listener(self.__on_tracks_added_or_deleted)
        self.song().add_record_mode_listener(self.__on_record_mode_changed)
        self.song().add_is_playing_listener(self.__on_is_playing_changed)
        self.song().add_loop_listener(self.__on_loop_changed)
        self.__reassign_strips()

        global mo
        mo = rtmidi.MidiOut()
        mo.open_port(0)

    def disconnect(self):
        self.song().remove_visible_tracks_listener(self.__on_tracks_added_or_deleted)
        self.song().remove_record_mode_listener(self.__on_record_mode_changed)
        self.song().remove_is_playing_listener(self.__on_is_playing_changed)
        self.song().remove_loop_listener(self.__on_loop_changed)
        for strip in self.__strips:
            strip.set_assigned_track(None)

        for track in self.__assigned_tracks:
            if track and track.name_has_listener(self.__on_track_name_changed):
                track.remove_name_listener(self.__on_track_name_changed)

    def remote_sl_parent(self):
        return self.__parent

    def receive_midi_cc(self, cc_no, cc_value):
        if cc_no in ts_ccs:
            self.__handle_transport_ccs(cc_no, cc_value)
        elif cc_no in mx_slider_row_ccs:
            channel_strip = self.__strips[cc_no - MX_SLIDER_ROW_BASE_CC]
            channel_strip.slider_moved(cc_value)
        elif cc_no in mx_first_button_row_ccs:
            channel_strip = self.__strips[cc_no - MX_FIRST_BUTTON_ROW_BASE_CC]
            if cc_value == CC_VAL_BUTTON_PRESSED:
                channel_strip.first_button_pressed()
        elif cc_no in mx_second_button_row_ccs:
            channel_strip = self.__strips[cc_no - MX_SECOND_BUTTON_ROW_BASE_CC]
            if cc_value == CC_VAL_BUTTON_PRESSED:
                channel_strip.second_button_pressed()
        elif cc_no in fx_upper_button_row_ccs:
            channel_strip = self.__strips[cc_no - FX_UPPER_BUTTON_ROW_BASE_CC]
            if cc_value == CC_VAL_BUTTON_PRESSED:
                channel_strip.solo_button_pressed()
        elif cc_no in fx_lower_button_row_ccs:
            channel_strip = self.__strips[cc_no - FX_LOWER_BUTTON_ROW_BASE_CC]
            if cc_value == NUM_CC_NO:
                channel_strip.stop_button_pressed()
                #channel_strip.select_button_pressed # switch with line above to select track for this button row
        elif cc_no in mx_display_button_ccs:
            self.__handle_page_up_down_ccs(cc_no, cc_value)
        else:
            print "unknown FX midi message"

    def receive_midi_note(self, note, velocity, note_onoff_status):
        if note_onoff_status == NOTE_ON_STATUS:
            if note == CA_METRONOME:
                self.ca_toggle_metronome()
            elif note == CA_TAP:
                self.ca_tap()
            elif note == CA_SAVE:
                self.ca_save()
            elif note == CA_UNDO:
                self.ca_undo()
            elif note == CA_ADD_AUDIO_TRACK:
                self.ca_addMidiTrack()
            elif note == CA_ADD_RETURN_TRACK:
                self.ca_addReturnTrack()
            elif note == CA_ADD_MIDI_TRACK:
                self.ca_addMidiTrack()

    def ca_toggle_metronome(self):
        if (self.song().metronome == 1):
            self.song().metronome = 0
        else:
            self.song().metronome = 1

    def ca_tap(self):
        self.song().tap_tempo()

    def ca_save(self):
        cmd = """
            osascript -e 'tell application "System Events" to keystroke "s" using {command down}' 
            """
        os.system(cmd)

    def ca_undo(self):
        if self.song().can_undo:
            self.song().undo()

    def ca_addAudioTrack(self):
        self.song().create_audio_track(-1)

    def ca_addReturnTrack(self):
        self.song().create_return_track()

    def ca_addMidiTrack(self):
        self.song().create_midi_track(-1)

    def build_midi_map(self, script_handle, midi_map_handle):
        needs_takeover = True
        for s in self.__strips:
            # Attach sliders
            cc_no = MX_SLIDER_ROW_BASE_CC + self.__strips.index(s)
            if s.assigned_track() and s.slider_parameter():
                map_mode = Live.MidiMap.MapMode.absolute
                parameter = s.slider_parameter()
                Live.MidiMap.map_midi_cc(midi_map_handle, parameter, SL_MIDI_CHANNEL, cc_no, map_mode, not needs_takeover)
            else:
                Live.MidiMap.forward_midi_cc(script_handle, midi_map_handle, SL_MIDI_CHANNEL, cc_no)
            # Attach encoders
            cc_no = FX_ENCODER_ROW_BASE_CC + self.__strips.index(s)
            if s.assigned_track() and s.encoder_parameter():
                map_mode = Live.MidiMap.MapMode.relative_smooth_signed_bit
                parameter = s.encoder_parameter()
                feedback_rule = Live.MidiMap.CCFeedbackRule()
                feedback_rule.cc_no = fx_encoder_feedback_ccs[self.__strips.index(s)]
                feedback_rule.channel = SL_MIDI_CHANNEL
                feedback_rule.delay_in_ms = 0
                feedback_rule.cc_value_map = tuple([ int(1.5 + float(index) / 127.0 * 10.0) for index in range(128) ])
                ring_mode_value = FX_RING_VOL_VALUE
                self.send_midi((self.cc_status_byte(), fx_encoder_led_mode_ccs[self.__strips.index(s)], ring_mode_value))
                Live.MidiMap.map_midi_cc_with_feedback_map(midi_map_handle, parameter, SL_MIDI_CHANNEL, cc_no, map_mode, feedback_rule, not needs_takeover)
                Live.MidiMap.send_feedback_for_parameter(midi_map_handle, parameter)
            else:
                Live.MidiMap.forward_midi_cc(script_handle, midi_map_handle, SL_MIDI_CHANNEL, cc_no)
            # Attach poties
            cc_no = FX_POTI_ROW_BASE_CC + self.__strips.index(s)
            if s.assigned_track() and s.potie_parameter():
                map_mode = Live.MidiMap.MapMode.absolute
                parameter = s.potie_parameter()
                Live.MidiMap.map_midi_cc(midi_map_handle, parameter, SL_MIDI_CHANNEL, cc_no, map_mode, not needs_takeover)
            else:
                Live.MidiMap.forward_midi_cc(script_handle, midi_map_handle, SL_MIDI_CHANNEL, cc_no)

        for cc_no in mx_forwarded_ccs + ts_ccs:
            Live.MidiMap.forward_midi_cc(script_handle, midi_map_handle, SL_MIDI_CHANNEL, cc_no)

        for note in fx_drum_pad_row_notes:
            Live.MidiMap.forward_midi_note(script_handle, midi_map_handle, SL_MIDI_CHANNEL, note)


    def refresh_state(self):
        self.__reassign_strips()
        self.__lock_enquiry_delay = 3

    def update_display(self):
        if self.__lock_enquiry_delay > 0:
            self.__lock_enquiry_delay -= 1
            if self.__lock_enquiry_delay == 0:
                self.send_midi((176, 103, 1)) # ask the SlMk about the transport lock status -> responds with cc 79
        if self.__rewind_button_down:
            self.song().jump_by(-FORW_REW_JUMP_BY_AMOUNT)
        if self.__forward_button_down:
            self.song().jump_by(FORW_REW_JUMP_BY_AMOUNT)
        #if self.song().is_playing:
        self.updateStopButtons() # this would be better called by an event listener

    def updateStopButtons(self):
        for s in self.__strips:
            if s.assigned_track() in tuple(self.song().tracks):
                if s.assigned_track().fired_slot_index == -2:
                    self.blink(FX_LOWER_BUTTON_ROW_BASE_CC + s.index())
                elif s.assigned_track().playing_slot_index >= 0:
                    mo.send_message((self.cc_status_byte(), FX_LOWER_BUTTON_ROW_BASE_CC + s.index(), NUM_CC_NO))
                else:
                    mo.send_message((self.cc_status_byte(), FX_LOWER_BUTTON_ROW_BASE_CC + s.index(), CC_VAL_BUTTON_RELEASED))

    def blink(self, led_index):
        if self.__blink == CC_VAL_BUTTON_RELEASED:
            self.__blink = NUM_CC_NO
        else:
            self.__blink = CC_VAL_BUTTON_RELEASED
        mo.send_message((self.cc_status_byte(), led_index, self.__blink))

    def __reassign_strips(self):
        track_index = self.__strip_offset
        track_names = []
        parameters = []
        for track in self.__assigned_tracks:
            if track and track.name_has_listener(self.__on_track_name_changed):
                track.remove_name_listener(self.__on_track_name_changed)

        self.__assigned_tracks = []
        all_tracks = tuple(self.song().visible_tracks) + tuple(self.song().return_tracks) + (self.song().master_track,)
        for s in self.__strips:
            if track_index < len(all_tracks):
                track = all_tracks[track_index]
                s.set_assigned_track(track)
                track_names.append(track.name)
                parameters.append(s.slider_parameter())
                track.add_name_listener(self.__on_track_name_changed)
                self.__assigned_tracks.append(track)
            else:
                s.set_assigned_track(None)
                track_names.append('')
                parameters.append(None)
            track_index += 1

        self.__display_controller.setup_left_display(track_names, parameters)
        self.request_rebuild_midi_map()
        
        page_up_value = CC_VAL_BUTTON_RELEASED
        page_down_value = CC_VAL_BUTTON_RELEASED
        if len(all_tracks) > NUM_CONTROLS_PER_ROW and self.__strip_offset < len(all_tracks) - NUM_CONTROLS_PER_ROW:
            page_up_value = CC_VAL_BUTTON_PRESSED
        if self.__strip_offset > 0:
            page_down_value = CC_VAL_BUTTON_PRESSED
        self.send_midi((self.cc_status_byte(), MX_DISPLAY_PAGE_UP, page_up_value))
        self.send_midi((self.cc_status_byte(), MX_DISPLAY_PAGE_DOWN, page_down_value))

    def __handle_page_up_down_ccs(self, cc_no, cc_value):
        all_tracks = tuple(self.song().visible_tracks) + tuple(self.song().return_tracks) + (self.song().master_track,)
        if cc_no == MX_DISPLAY_PAGE_UP:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                if len(all_tracks) > NUM_CONTROLS_PER_ROW and self.__strip_offset < len(all_tracks) - NUM_CONTROLS_PER_ROW:
                    self.__strip_offset += NUM_CONTROLS_PER_ROW
                    self.__validate_strip_offset()
                    self.__reassign_strips()
        elif cc_no == MX_DISPLAY_PAGE_DOWN:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                if len(all_tracks) > NUM_CONTROLS_PER_ROW and self.__strip_offset > 0:
                    self.__strip_offset -= NUM_CONTROLS_PER_ROW
                    self.__validate_strip_offset()
                    self.__reassign_strips()

    def __handle_transport_ccs(self, cc_no, cc_value):
        if cc_no == TS_REWIND_CC:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                self.__rewind_button_down = True
                self.song().jump_by(-FORW_REW_JUMP_BY_AMOUNT)
            else:
                self.__rewind_button_down = False
        elif cc_no == TS_FORWARD_CC:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                self.__forward_button_down = True
                self.song().jump_by(FORW_REW_JUMP_BY_AMOUNT)
            else:
                self.__forward_button_down = False
        elif cc_no == TS_STOP_CC:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                self.song().stop_playing()
        elif cc_no == TS_PLAY_CC:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                self.song().start_playing()
        elif cc_no == TS_LOOP_CC:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                self.song().loop = not self.song().loop
        elif cc_no == TS_RECORD_CC:
            if cc_value == CC_VAL_BUTTON_PRESSED:
                self.song().record_mode = not self.song().record_mode
        elif cc_no == TS_LOCK:
            self.__transport_locked = (cc_value != CC_VAL_BUTTON_RELEASED)
            self.__on_transport_lock_changed()
        else:
            raise False or AssertionError, 'unknown Transport CC ' + str(cc_no)

    def __on_transport_lock_changed(self):
        for strip in self.__strips:
            strip.take_control_of_second_button(not self.__transport_locked)

        if self.__transport_locked:
            self.__on_is_playing_changed()
            self.__on_loop_changed()
            self.__on_record_mode_changed()
            
    def __on_tracks_added_or_deleted(self):
        self.__validate_strip_offset()
        self.__reassign_strips()

    def __on_track_name_changed(self):
        self.__reassign_strips()

    def __validate_strip_offset(self):
        all_tracks = tuple(self.song().visible_tracks) + tuple(self.song().return_tracks) + (self.song().master_track,)
        self.__strip_offset = min(self.__strip_offset, len(all_tracks) - 1)
        self.__strip_offset = max(0, self.__strip_offset)

    def __on_record_mode_changed(self):
        if self.__transport_locked:
            if self.song().record_mode:
                self.send_midi((self.cc_status_byte(), 53, 1))
            else:
                self.send_midi((self.cc_status_byte(), 53, 0))

    def __on_is_playing_changed(self):
        if self.__transport_locked:
            if self.song().is_playing:
                self.send_midi((self.cc_status_byte(), 51, CC_VAL_BUTTON_PRESSED))
                self.send_midi((self.cc_status_byte(), 50, CC_VAL_BUTTON_RELEASED))
            else:
                self.send_midi((self.cc_status_byte(), 51, CC_VAL_BUTTON_RELEASED))
                self.send_midi((self.cc_status_byte(), 50, CC_VAL_BUTTON_PRESSED))

    def __on_loop_changed(self):
        if self.__transport_locked:
            if self.song().loop:
                self.send_midi((self.cc_status_byte(), 52, CC_VAL_BUTTON_PRESSED))
            else:
                self.send_midi((self.cc_status_byte(), 52, CC_VAL_BUTTON_RELEASED))

    def is_arm_exclusive(self):
        return self.__parent.song().exclusive_arm

    def is_solo_exclusive(self):
        return self.__parent.song().exclusive_solo

    def set_selected_track(self, track):
        if track:
            self.__parent.song().view.selected_track = track

    def track_about_to_arm(self, track):
        if track and self.__parent.song().exclusive_arm:
            for t in self.__parent.song().tracks:
                if t.can_be_armed and t.arm and not t == track:
                    t.arm = False

    def track_about_to_solo(self, track):
        if track and self.__parent.song().exclusive_solo:
            for t in self.__parent.song().tracks:
                if t.solo and not t == track:
                    t.solo = False


class MixerChannelStrip():
    """Represents one of the 8 track related strips in the Mixer controls (one slider,
    two buttons)
    """
    def __init__(self, mixer_controller_parent, index):
        self.__mixer_controller = mixer_controller_parent
        self.__index = index
        self.__assigned_track = None
        self.__control_second_button = True

    def index(self):
        return self.__index

    def song(self):
        return self.__mixer_controller.song()

    def assigned_track(self):
        return self.__assigned_track

    def set_assigned_track(self, track):
        if self.__assigned_track != None:
            if self.__assigned_track != self.song().master_track:
                self.__assigned_track.remove_mute_listener(self._on_mute_changed)
                self.__assigned_track.remove_solo_listener(self._on_solo_changed)
            if self.__assigned_track.can_be_armed:
                self.__assigned_track.remove_arm_listener(self._on_arm_changed)
        self.__assigned_track = track
        if self.__assigned_track != None:
            if self.__assigned_track != self.song().master_track:
                self.__assigned_track.add_mute_listener(self._on_mute_changed)
                self.__assigned_track.add_solo_listener(self._on_solo_changed)
            if self.__assigned_track.can_be_armed:
                self.__assigned_track.add_arm_listener(self._on_arm_changed)
        self._on_mute_changed()
        self._on_arm_changed()

    def slider_parameter(self):
        return self.__assigned_track.mixer_device.volume

    def encoder_parameter(self):
        if len(self.__assigned_track.mixer_device.sends) > 0:
            return self.__assigned_track.mixer_device.sends[0]
        else:
            return None

    def potie_parameter(self):
        return self.__assigned_track.mixer_device.panning

    def slider_moved(self, cc_value):
        pass

    def take_control_of_second_button(self, take_control):
        self.__mixer_controller.remote_sl_parent().send_midi((self.__mixer_controller.cc_status_byte(), self.__index + MX_SECOND_BUTTON_ROW_BASE_CC, 0))
        self.__control_second_button = take_control
        self._on_mute_changed()
        self._on_arm_changed()

    def first_button_pressed(self):
        if self.__assigned_track:
            if self.__assigned_track in tuple(self.song().visible_tracks) + tuple(self.song().return_tracks):
                self.__assigned_track.mute = not self.__assigned_track.mute

    def second_button_pressed(self):
        if self.__assigned_track in self.song().visible_tracks:
            if self.__assigned_track.can_be_armed:
                self.__mixer_controller.track_about_to_arm(self.__assigned_track)
                self.__assigned_track.arm = not self.__assigned_track.arm
                if self.__assigned_track.arm:
                    self.__assigned_track.view.select_instrument() and self.__mixer_controller.set_selected_track(self.__assigned_track)

    def solo_button_pressed(self):
        if self.__assigned_track:
            if self.__assigned_track in tuple(self.song().visible_tracks) + tuple(self.song().return_tracks):
                self.__mixer_controller.track_about_to_solo(self.__assigned_track)
                self.__assigned_track.solo = not self.__assigned_track.solo

    def stop_button_pressed(self):
        if self.__assigned_track:
            if self.__assigned_track in tuple(self.song().visible_tracks) + (self.song().master_track,):
                if self.__assigned_track == self.song().master_track:
                    self.song().stop_all_clips()
                else:
                    self.__assigned_track.stop_all_clips()
    
    def select_button_pressed(self):
        if self.__assigned_track:
            if self.__assigned_track in tuple(self.song().visible_tracks) + tuple(self.song().return_tracks) + (self.song().master_track,):
                self.__mixer_controller.set_selected_track(self.__assigned_track)

    def _on_mute_changed(self):
        value = CC_VAL_BUTTON_RELEASED
        if self.__assigned_track in tuple(self.song().tracks) + tuple(self.song().return_tracks) and not self.__assigned_track.mute:
            value = CC_VAL_BUTTON_PRESSED
        self.__mixer_controller.remote_sl_parent().send_midi((self.__mixer_controller.cc_status_byte(), self.__index + MX_FIRST_BUTTON_ROW_BASE_CC, value))

    def _on_arm_changed(self):
        if self.__control_second_button:
            value = CC_VAL_BUTTON_RELEASED
            if self.__assigned_track and self.__assigned_track in self.song().tracks and self.__assigned_track.can_be_armed and self.__assigned_track.arm:
                value = CC_VAL_BUTTON_PRESSED
            self.__mixer_controller.remote_sl_parent().send_midi((self.__mixer_controller.cc_status_byte(), self.__index + MX_SECOND_BUTTON_ROW_BASE_CC, value))

    def _on_solo_changed(self):
        value = CC_VAL_BUTTON_RELEASED
        if self.__assigned_track in tuple(self.song().tracks) and self.__assigned_track.solo:
            value = NUM_CC_NO
        self.__mixer_controller.remote_sl_parent().send_midi((self.__mixer_controller.cc_status_byte(), self.__index + FX_UPPER_BUTTON_ROW_BASE_CC, value))