"""Single fail-closed camera diagnostic. Default never opens a serial port.

Currently installed/reported probe firmware cannot produce SNC1 capture packets.
A gated, unflashed capture core is now prepared. Do not use
--run until the independent physical gates and actual capture firmware exist.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.camera.hardware_gate import BLOCKER, load_approval


def preparation():
    return dict(state="blocked",evidence_source="preparation_only",serial_opened=False,
        serial_port_access="not_tested",camera_responder_communication="not_tested",
        camera_status_received=False,camera_initialization="not_tested",sensor_pid=None,
        first_valid_jpeg=False,sustained_delivery=False,observed_fps=None,resolution=None,
        hardware_operations_performed=False,error=BLOCKER)


def observe(source, seconds, clock=time.monotonic, *, first_frame_only=False, save_first_jpeg=None):
    start=clock();first=last=None;frames=0
    primary_error=None
    artifact={}
    try:
        source.open()
        while clock()-start<seconds:
            ok,frame=source.read_frame()
            if ok:
                now=clock()
                if first is None:first=now
                last=now;frames+=1
                if frames == 1 and save_first_jpeg is not None:
                    # Preserve received JPEG bytes, never a re-encoded preview.
                    payload=source.last_jpeg
                    if not payload:raise RuntimeError("Decoded frame has no original JPEG payload")
                    path=Path(save_first_jpeg)
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open("xb") as handle:handle.write(payload)
                    artifact=dict(first_jpeg_file=str(path.resolve()),
                        first_jpeg_sha256=hashlib.sha256(payload).hexdigest(),
                        first_jpeg_bytes=len(payload),first_jpeg_metadata=dict(source.frame_metadata))
                if first_frame_only:break
        stats=source.snapshot()
        span=last-first if frames else 0
        sustained=frames>=3 and span>=5 and stats.get("reconnects",0)==0
        return dict(state="first_frame_received" if first_frame_only and frames else "passed" if sustained else "incomplete",
            evidence_source=stats.get("evidence_source","not_tested"),
            serial_opened=source.port_opened,
            serial_port_access="opened" if source.port_opened else "unconfirmed",
            camera_responder_communication=("passed_matching_camera_pong" if stats.get("camera_responder_verified") else "awaiting_matching_camera_pong" if stats.get("responder_challenged") else "not_tested_no_ping_transmitted"),
            camera_status_received=stats["sensor_pid_reported"] is not None,
            camera_initialization=stats["camera_initialization_reported"],
            sensor_pid=stats["sensor_pid_reported"],first_valid_jpeg=frames>0,
            sustained_delivery=sustained,valid_jpegs=frames,
            observation_s=span,observed_fps=(frames-1)/span if span else None,
            resolution=[source.frame_width,source.frame_height] if frames else None,
            source_metrics=stats,**artifact)
    except BaseException as exc:
        primary_error=exc
        raise
    finally:
        try:source.close()
        except RuntimeError as cleanup_error:
            if primary_error is not None:
                raise RuntimeError(str(primary_error)+"; cleanup unconfirmed: "+str(cleanup_error)) from primary_error
            raise


def stages(result):
    prerequisite="operator_verified" if result.get("hardware_prerequisites_verified") else "unverified"
    response=result.get("camera_responder_communication","not_tested")
    return {
        "power_and_hardware":dict(state=prerequisite,source="operator evidence, not a voltage measurement"),
        "com_port":dict(state=result.get("com_port_availability","not_checked"),access=result.get("serial_port_access","not_tested")),
        "camera_responder":dict(state=response),
        "sensor_initialization":dict(state=result.get("camera_initialization","not_tested"),pid=result.get("sensor_pid"),evidence="device report only"),
        "first_jpeg":dict(state="received_and_decoded" if result.get("first_valid_jpeg") else "not_received"),
        "sustained_frames":dict(state="observed" if result.get("sustained_delivery") else "not_verified",fps=result.get("observed_fps"),resolution=result.get("resolution"),frame_age_s=(result.get("source_metrics") or {}).get("frame_age_s"),dropped=(result.get("source_metrics") or {}).get("dropped_frames")),
        "dashboard_display":dict(state="not_tested_by_serial_checker"),
        "detector_tracker_events_evidence":dict(state="not_tested_by_serial_checker"),
        "florence_smollm2":dict(state="not_tested_by_serial_checker")}


def enumerate_ports():
    # OS device enumeration only: no Serial constructor, port opening or writes.
    from serial.tools import list_ports
    return [dict(port=p.device,description=p.description,vid=p.vid,pid=p.pid) for p in list_ports.comports()]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--list-ports",action="store_true",help="Read OS port metadata without opening any port")
    parser.add_argument("--allow-serial-open",action="store_true")
    parser.add_argument("--power-verified",action="store_true")
    parser.add_argument("--firmware-verified",action="store_true")
    parser.add_argument("--seconds",type=float,default=30)
    parser.add_argument("--first-frame",action="store_true",help="Stop after the first decoded JPEG; does not qualify sustained video")
    parser.add_argument("--save-first-jpeg",type=Path,help="Save exact first decoded JPEG to a NEW file; never overwrite an existing file")
    args=parser.parse_args(argv)
    if not 6<=args.seconds<=120:parser.error("--seconds must be6..120")
    result=preparation()
    diagnostics_path=None
    if args.run:
        if not (args.allow_serial_open and args.power_verified and args.firmware_verified):
            result["error"]="Requires --allow-serial-open --power-verified --firmware-verified plus independent hardware approval"
        else:
            source=None
            try:
                approval=load_approval(ROOT)
                result["hardware_prerequisites_verified"]=True
                from backend.camera.esp32_uart import Esp32CameraSource
                source=Esp32CameraSource(approval)
                result=observe(source,args.seconds,first_frame_only=args.first_frame,save_first_jpeg=args.save_first_jpeg)
                result.update(evidence_source="live_serial",port=approval["port"],
                    camera_id=approval["camera_id"],finished_at=time.time(),
                    hardware_prerequisites_verified=True,hardware_operations_performed=True)
            except (ValueError,OSError,RuntimeError) as exc:
                result.update(state="blocked" if isinstance(exc,ValueError) else "error",error=str(exc))
            finally:
                if source is not None:
                    stats=source.snapshot()
                    result.update(serial_port_access="opened" if source.port_opened else "failed_to_open",
                        first_valid_jpeg=source.decoded_frames>0,valid_jpegs=source.decoded_frames,
                        camera_initialization=stats["camera_initialization_reported"],
                        sensor_pid=stats["sensor_pid_reported"],last_frame_metadata=source.frame_metadata,
                        camera_status_received=stats["sensor_pid_reported"] is not None,
                        camera_responder_communication=("passed_matching_camera_pong" if stats.get("camera_responder_verified") else "awaiting_matching_camera_pong" if stats.get("responder_challenged") else "not_tested_no_ping_transmitted"))
                    result.update(serial_opened=source.port_opened,
                        hardware_operations_performed=source.access_attempted,
                        evidence_source="live_serial",port=approval["port"],
                        camera_id=approval["camera_id"],finished_at=time.time())
                    diagnostics_path=ROOT/"data/hardware_identification/camera_live_diagnostics.json"
    if args.list_ports:
        try:
            ports=enumerate_ports()
            result["available_ports"]=ports
            selected=result.get("port","COM9")
            result["com_port_availability"]="enumerated" if any(p["port"].casefold()==selected.casefold() for p in ports) else "not_enumerated"
        except (OSError,ImportError) as exc:
            result["com_port_availability"]="enumeration_error"
            result["port_enumeration_error"]=str(exc)
    result["stages"]=stages(result)
    result["reported_power_path"]="power bank USB -> ESP-B USB -> ESP-B5V/GND -> CAM5V/GND (reported, not measured)"
    result["reported_data_path"]="laptop USB -> ESP-A CH9102; ESP-A EN-GND; reported GPIO3/RX0->CAM U0R / GPIO1/TX0<-CAM U0T; ESP-A GND->ESP-B GND->CAM GND; corrected adapter direction reported, not yet ROM-tested; old GPIO16/17 removed"
    if diagnostics_path is not None:
        diagnostics_path.parent.mkdir(parents=True,exist_ok=True)
        diagnostics_path.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    return 0 if result["state"] in ("passed","first_frame_received") else 2


if __name__=="__main__":raise SystemExit(main())
